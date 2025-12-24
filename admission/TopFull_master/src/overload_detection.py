from admission_controller import kubeAPI
from resource_collector import *
from metric_collector import Collector

import os
import sys
import json
import subprocess
import pickle
import time

import shield

global_config_path = os.environ["GLOBAL_CONFIG_PATH"]
with open(global_config_path, "r") as f:
    global_config = json.load(f)

from pathlib import Path

# Include the controller-helpers directory in the path.
helpers_path = Path(__file__).parent / ".." / ".." / ".." / "controller-helpers"
sys.path.append(str(helpers_path.resolve()))

import common_utils

"""
CPU quota in this experiment is fixed to 200mi.
Dynamic quota probing is not developed yet
"""
cpu_quota = 200

proxy_rate_dir = os.path.expanduser(global_config["proxy_dir"])

microservice_code = global_config["microservice_code"]

# Higher priority has larger values
if microservice_code == "online_boutique":
    # Online Boutique
    business_priority = {
        "postcheckout": 0,
        "getcart": 0,
        "postcart": 0,
        "getproduct": 0,
        "emptycart": 0
    }
elif microservice_code == "train_ticket":
    # Train Ticket
    business_priority = {
        'high_speed_ticket': 0,
        'normal_speed_ticket': 0,
        'query_cheapest': 0,
        'query_min_station': 0,
        'query_quickest': 0,
        'query_order': 0,
        'query_order_other': 0,
        'query_route': 0,
        'query_food': 0,
        'enter_station': 0,
        'preserve_normal': 0,
        'query_contact': 0,
        'query_payment': 0
    }
elif microservice_code == "hotel_reservation":
    # Hotel Reservation
    business_priority = {
        'user': 0,
        'search': 0,
        'reserve': 0,
        'recommend': 0,
    }
elif microservice_code == "social_network":
    # Social Network
    business_priority = {
        'compose_post': 0,
        'read_home_timeline': 0,
        'read_user_timeline': 0,
    }

log_file = Path.home() / "out" / "shield_info.txt"

def apply_threshold_proxy(curr_limits, apis, use_shield=False, test=False):
    new_limits = curr_limits.copy()
    for api in apis:
        if api['threshold'] <= 10:
            api['threshold'] = 10

        new_limits[api['name']] = int(api['threshold'])

    # Return False if shield not activated.
    shield_activated = False

    # Verify the new limits under the shield.
    if use_shield:
        if microservice_code == "hotel_reservation":
            app = "reservation"
        elif microservice_code == "social_network":
            app = "social"
        else:
            app = microservice_code

        # We need the current parameters to verify the new limits.
        # Read the params from curr_params.pkl file. If file is absent,
        # or if the timestamp is old, call the stub to get latencies and
        # update the file.
        params_file = helpers_path / "curr_params.pkl"
        params_file = str(params_file.resolve())
        curr_params = None
        params_valid = False

        if os.path.exists(params_file):
            try:
                with open(params_file, "rb") as pf:
                    curr_params = pickle.load(pf)
                # Check if the params are recent (e.g., within last 60 seconds)
                file_mtime = os.path.getmtime(params_file)
                if time.time() - file_mtime < 60:
                    params_valid = True
            except Exception as e:
                print(f"Error loading params file: {e}")
                curr_params = None

        if not params_valid or curr_params is None:
            with open(log_file, "a") as logf:
                logf.write("[INFO] Fetching new parameters from the collector...\n")
            collector = Collector(microservice_code, type="grpc", use_certificates=False)

            # Call the stub to get latencies and update the file
            curr_params = collector.fetch_params(period=60)
            with open(params_file, "wb") as pf:
                pickle.dump(curr_params, pf)

        robust, new_limits = shield.verify_and_propose_ratelimit_action(
            curr_params,
            curr_limits,
            new_limits,
            delta=0.1,
            slo=100,
            app=app
        )

        if not robust:
            shield_activated = True
            with open(log_file, "a") as logf:
                logf.write("[INFO] SHIELD ACTIVATED.\n")

    # Now update the proxy rate limit files.
    for api in apis:
        # Call the utils script to change the rate limit.
        common_utils.change_rate_limit(api['name'], new_limits[api['name']])

        print(f"{api['name']}: {api['threshold']}")

    # Return the new limits.
    return new_limits, shield_activated

class Detector:
    """
    Initiate detector
    Parameters
    - config: filepath of configuration file, which contains microservices information

    1) Get all services to monitor
    2) Get execution path of APIs
    3) Initialize kubernetes client
    """
    def __init__(self, use_shield=False, config=global_config["microservice_configuration"]):
        self.kube = kubeAPI()

        self.use_shield = use_shield

        rps = self.current_rps()

        # self.event = threading.Event()
        # t = threading.Thread(target=run, args=(self.event,))
        # t.start()
        # self.tid = t

        with open(os.path.expanduser(config), "r") as f:
            data = json.load(f)
        self.services = {}
        for svc in data['data']['services']:
            self.services[svc] = {
                'namespace': 'default',
                'cpu': 1000,
                'apis': []
            }

        self.apis = {}
        self.curr_limits = {}
        for api in data['data']['api']:
            self.apis[api['name']] = {
                'method': api['method'],
                'url': api['url'],
                'execution_path': api['execution_path'],
                'threshold': rps.get(api['name'], 10000),
                'name': api['name']
            }
            self.curr_limits[api['name']] = self.apis[api['name']]['threshold']

        for svc in list(self.services.keys()):
            for api in list(self.apis.keys()):
                if svc in self.apis[api]['execution_path']:
                    self.services[svc]['apis'].append(api)

        # Experimental Setup, it should match CPU quota unit in yaml files of benchmark applications
        if microservice_code == "online_boutique":
            # Online Boutique
            self.services['cartservice']['cpu'] = 1000
            self.services['currencyservice']['cpu'] = 1000
            self.services['frontend']['cpu'] = 1000
            self.services['adservice']['cpu'] = 1000
            self.services['productcatalogservice']['cpu'] = 500
            self.services['checkoutservice']['cpu'] = 1000
            self.services['recommendationservice']['cpu'] = 2000
        elif microservice_code == "train_ticket":
            # Train Ticket
            self.services['ts-order-service']['cpu'] = 500
            self.services['ts-station-service']['cpu'] = 500
            self.services['ts-order-other-service']['cpu'] = 500
            self.services['ts-travel-service']['cpu'] = 1000
            self.services['ts-travel2-service']['cpu'] = 500
            self.services['ts-contacts-service']['cpu'] = 500
            self.services['ts-food-service']['cpu'] = 500
            self.services['ts-inside-payment-service']['cpu'] = 500
            self.services['ts-food-map-service']['cpu'] = 1000
        elif microservice_code == "hotel_reservation":
            # Hotel Reservation
            self.services['frontend']['cpu'] = 1000
            self.services['search']['cpu'] = 500
            self.services['reservation']['cpu'] = 500
            self.services['recommendation']['cpu'] = 500
            self.services['user']['cpu'] = 500
            self.services['profile']['cpu'] = 500
            self.services['geo']['cpu'] = 500
            self.services['rate']['cpu'] = 500
        elif microservice_code == "social_network":
            # Social Network
            self.services['nginx-thrift']['cpu'] = 2000
            self.services['compose-post-service']['cpu'] = 1000
            self.services['home-timeline-service']['cpu'] = 1000
            self.services['media-frontend']['cpu'] = 1000
            self.services['media-service']['cpu'] = 1000
            self.services['post-storage-service']['cpu'] = 1000
            self.services['social-graph-service']['cpu'] = 1000
            self.services['text-service']['cpu'] = 1000
            self.services['unique-id-service']['cpu'] = 1000
            self.services['url-shorten-service']['cpu'] = 1000
            self.services['user-mention-service']['cpu'] = 1000
            self.services['user-service']['cpu'] = 1000
            self.services['user-timeline-service']['cpu'] = 1000

        return
    
    """
    Find overloaded services among the registered services according to 
    CPU usage and CPU quota for each services.
    If CPU usage per a pod > CPU quota  * alpha, it is overloaded

    Return: List of overloaded service
    """
    def detect(self, alpha=0.9):
        # Fetch CPU quota and CPU usage of all services
        result = []
        resources = self.get_cpu_util(list(self.services.keys()))
        print("Resource usage: ", resources)
        for svc in list(resources.keys()):
            usage = resources[svc]['cpu']
            quota = self.services[svc]['cpu']
            if svc == "productcatalogservice" or svc == "cartservice":
                target = 0.95
            else:
                target = alpha
            if usage > quota * target:
                result.append(svc)
        print(result)
        return result
    
    """
    Find APIs which use the overloaded services
    """
    def clustering(self, services):
        result = []
        for svc in services:
            result += self.services[svc]['apis']

        target_apis = list(set(result))
        ret = []
        rps = self.current_rps()
        # print(rps)
        for api in target_apis:
            if api == "frontend":
                continue
            if rps.get(api, 0) > 0:
                ret.append(api) 
        return ret
    
    """
    Set priority to target APIs, which pass through overloaded services
    """
    def set_priority(self, apis, services):
        result = []
        if len(services) == 0:
            for api in apis:
                result.append((api, 0, business_priority[api]))
        else:
            for api in apis:
                tmp_list = [100]
                for service in self.apis[api]['execution_path']:
                    if service in services:
                        tmp_list.append(len(self.services[service]['apis']))
                result.append((api, min(tmp_list), business_priority[api]))
        return result
    
    """
    Get CPU utilization of each pod with 'kubectl top pod' command
    """
    def get_cpu_util(self, targets):
        output = str(subprocess.check_output('kubectl top pod', shell=True), 'utf-8')
        output = output.split("\n")
        result = {}
        for svc in list(self.services.keys()):
            result[svc] = {'cpu': 0, 'replicas': 0}
        for out in output:
            out = out.split()
            if len(out) != 3:
                continue
            if out[0] == 'NAME':
                continue
            
            name = '-'.join(out[0].split('-')[:-2])
            cpu = int(out[1][:-1])
            if name in targets:
                if cpu < 20:
                    continue
                if name in result:
                    result[name]['cpu'] += cpu
                    result[name]['replicas'] += 1

        
        for key in list(result.keys()):
            if result[key]['replicas'] > 0:
                result[key]['cpu'] /= result[key]['replicas']
        return result
    

    def get_cpu_util_v2(self, targets):
        result = {}
        for service in targets:
            try:
                result[service] = cpu_util[service]
            except:
                result[service] = 0
        return result
    

    """
    Apply action from RL
    """
    def apply(self, action, target_apis, overloaded_services, test=False):
        overloaded_services_tmp = self.detect(0.9)
        priority = self.set_priority(target_apis, overloaded_services_tmp)
        if len(priority) == 0:
            return
        priority.sort(key=lambda x: x[1]*1000 + x[2])

        if action < 0:
            min_val = priority[0][1]
            target = [priority[0][0]]
            result = [self.apis[priority[0][0]]]

            i = 1
            while i <= len(priority)-1:
                if min_val == priority[i][1] and priority[0][2] == priority[i][2]:
                    target.append(priority[i][0])
                    result.append(self.apis[priority[i][0]])
                    i += 1
                else:
                    break
            
            # Assign action to top-priority APIs
            action *= -1
            leftover = action
            while leftover > 0 and len(target) > 0:
                tmp = leftover / len(target)
                leftover = tmp * len(target)
                remove = []
                for api in target:
                    if self.apis[api]['threshold'] >= tmp:
                        self.apis[api]['threshold'] -= tmp
                        leftover -= tmp
                    else:
                        leftover -= self.apis[api]['threshold']
                        self.apis[api]['threshold'] = 0
                        remove.append(api)
                for api in remove:
                    target.remove(api)
            
            # Assign leftover action to other APIs
            while leftover > 0 and i <= len(priority)-1:
                targetAPI = priority[i][0]
                if self.apis[targetAPI]['threshold'] >= leftover:
                    self.apis[targetAPI]['threshold'] -= leftover
                    leftover = 0
                    result.append(self.apis[targetAPI])
                    break
                else:
                    leftover -= self.apis[targetAPI]['threshold']
                    self.apis[targetAPI]['threshold'] = 0
                    result.append(self.apis[targetAPI])
                    i += 1

            if leftover > 0:
                print(f"Wrong action, leftover: {leftover}")
            self.curr_limits, _ = apply_threshold_proxy(self.curr_limits, result, use_shield=self.use_shield, test=test)

        elif action > 0:
            priority.reverse()
            max_val = priority[0][1]
            target = [priority[0][0]]
            result = [self.apis[priority[0][0]]]

            i = 1
            while i <= len(priority)-1:
                if max_val == priority[i][1] and priority[0][2] == priority[i][2]:
                    target.append(priority[i][0])
                    result.append(self.apis[priority[i][0]])
                    i += 1
                else:
                    break
            
            rps = self.current_rps()
            leftover = action
            margin = 1.1
            while leftover > 0 and len(target) > 0:
                tmp = leftover / len(target)
                leftover = tmp * len(target)
                remove = []
                for api in target:
                    if self.apis[api]['threshold'] + tmp <= rps.get(api, 0) * margin:
                        self.apis[api]['threshold'] += tmp
                        leftover -= tmp
                    else:
                        apply = rps.get(api, 0)*margin - self.apis[api]['threshold']
                        self.apis[api]['threshold'] = rps.get(api, 0) * margin
                        leftover -= apply
                        remove.append(api)
                for api in remove:
                    target.remove(api)
            
            while leftover > 0 and i <= len(priority)-1:
                targetAPI = priority[i][0]
                if self.apis[targetAPI]['threshold'] + leftover <= rps.get(targetAPI, 0) * margin:
                    self.apis[targetAPI]['threshold'] += leftover
                    leftover = 0
                    result.append(self.apis[targetAPI])
                    break
                else:
                    apply = rps.get(targetAPI, 0)*margin - self.apis[targetAPI]['threshold']
                    self.apis[targetAPI]['threshold'] = rps.get(targetAPI, 0)*margin
                    leftover -= apply
                    result.append(self.apis[targetAPI])
                    i += 1
            if leftover > 0:
                print(f"Wrong action, leftover: {leftover}")


            self.curr_limits, _ = apply_threshold_proxy(self.curr_limits, result, use_shield=self.use_shield)


    def apply_v2(self, action, target_apis, overloaded_services, test=False):
        overloaded_services_tmp = self.detect(0.8)
        priority = self.set_priority(target_apis, overloaded_services_tmp)
        if len(priority) == 0:
            return
        priority.sort(key=lambda x: x[1]*1000 + x[2])
        print(priority)
        if action < 0:
            target = [priority[0][0]]
            min_val = priority[0][1]
            i = 1
            while i <= len(priority)-1:
                if min_val == priority[i][0] and priority[0][2] == priority[i][2]:
                    target.append(priority[i][0])
                    i += 1
                else:
                    break
        else:
            priority.reverse()
            target = [priority[0][0]]
            min_val = priority[0][1]
            i = 1
            while i <= len(priority)-1:
                if min_val == priority[i][0] and priority[0][2] == priority[i][2]:
                    target.append(priority[i][0])
                    i += 1
                else:
                    break
            priority.reverse()
        
        total_rps = 0
        for api in target:
            total_rps += self.apis[api]['threshold']
        action = action * total_rps

        if action < 0:
            min_val = priority[0][1]
            target = [priority[0][0]]
            result = [self.apis[priority[0][0]]]

            i = 1
            while i <= len(priority)-1:
                if min_val == priority[i][1] and priority[0][2] == priority[i][2]:
                    target.append(priority[i][0])
                    result.append(self.apis[priority[i][0]])
                    i += 1
                else:
                    break
            
            # Assign action to top-priority APIs
            action *= -1
            leftover = action
            while leftover > 0 and len(target) > 0:
                tmp = leftover / len(target)
                leftover = tmp * len(target)
                remove = []
                for api in target:
                    if self.apis[api]['threshold'] >= tmp:
                        self.apis[api]['threshold'] -= tmp
                        leftover -= tmp
                    else:
                        leftover -= self.apis[api]['threshold']
                        self.apis[api]['threshold'] = 0
                        remove.append(api)
                for api in remove:
                    target.remove(api)
            
            # Assign leftover action to other APIs
            while leftover > 0 and i <= len(priority)-1:
                targetAPI = priority[i][0]
                if self.apis[targetAPI]['threshold'] >= leftover:
                    self.apis[targetAPI]['threshold'] -= leftover
                    leftover = 0
                    result.append(self.apis[targetAPI])
                    break
                else:
                    leftover -= self.apis[targetAPI]['threshold']
                    self.apis[targetAPI]['threshold'] = 0
                    result.append(self.apis[targetAPI])
                    i += 1

            if leftover > 0:
                print(f"Wrong action, leftover: {leftover}")
            self.curr_limits, _ = apply_threshold_proxy(self.curr_limits, result, use_shield=self.use_shield, test=test)

        elif action > 0:
            priority.reverse()
            max_val = priority[0][1]
            target = [priority[0][0]]
            result = [self.apis[priority[0][0]]]

            i = 1
            while i <= len(priority)-1:
                if max_val == priority[i][1] and priority[0][2] == priority[i][2]:
                    target.append(priority[i][0])
                    result.append(self.apis[priority[i][0]])
                    i += 1
                else:
                    break
            
            rps = self.current_rps()
            leftover = action
            margin = 1.1
            while leftover > 0 and len(target) > 0:
                tmp = leftover / len(target)
                leftover = tmp * len(target)
                remove = []
                for api in target:
                    if self.apis[api]['threshold'] + tmp <= rps.get(api, 0) * margin:
                        self.apis[api]['threshold'] += tmp
                        leftover -= tmp
                    else:
                        apply = rps.get(api, 0)*margin - self.apis[api]['threshold']
                        self.apis[api]['threshold'] = rps.get(api, 0) * margin
                        leftover -= apply
                        remove.append(api)
                for api in remove:
                    target.remove(api)
            
            while leftover > 0 and i <= len(priority)-1:
                targetAPI = priority[i][0]
                if self.apis[targetAPI]['threshold'] + leftover <= rps.get(targetAPI, 0) * margin:
                    self.apis[targetAPI]['threshold'] += leftover
                    leftover = 0
                    result.append(self.apis[targetAPI])
                    break
                else:
                    apply = rps.get(targetAPI, 0)*margin - self.apis[targetAPI]['threshold']
                    self.apis[targetAPI]['threshold'] = rps.get(targetAPI, 0)*margin
                    leftover -= apply
                    result.append(self.apis[targetAPI])
                    i += 1
            if leftover > 0:
                print(f"Wrong action, leftover: {leftover}")


            self.curr_limits, _ = apply_threshold_proxy(self.curr_limits, result, use_shield=self.use_shield)
       
        print(overloaded_services_tmp)

    
    def current_rps(self):
        proxies = {
            'http': global_config["proxy_url"]
        }
        url = global_config["proxy_url"] + "/stats"

        result = {}
        response = requests.get(url, proxies=proxies)
        if not response.ok:
            return None
        body = response.text
        body = body.split("/")[:-1]
        for elem in body:
            elem = elem.split("=")
            result[elem[0]] = float(elem[1])
        
        return result

    """
    Set threshold of APIs to initial threshold
    """
    def reset(self, target=None):
        if target == None:
            self.curr_limits, _ = apply_threshold_proxy(self.curr_limits, list(self.apis.values()))
        else:
            target_apis = []
            for api in target:
                target_apis.append(self.apis[api])
            self.curr_limits, _ = apply_threshold_proxy(self.curr_limits, target_apis)


def main():
    # proxies = {
    #     'http': 'http://egg3.kaist.ac.kr:8090'
    # }
    # url = "http://egg3.kaist.ac.kr:8090/thresholds"
    # response = requests.get(url, proxies=proxies)
    d = Detector()
    print(d.current_rps())
    quit()
    while True:
        time.sleep(1)
        print(d.detect())

if __name__ == "__main__":
    main()




