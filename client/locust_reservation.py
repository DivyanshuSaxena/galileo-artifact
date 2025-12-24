from locust import HttpUser, LoadTestShape, task, events
import locust.stats
import random
import logging
import time
import json
import socket

from pathlib import Path

locust.stats.CONSOLE_STATS_INTERVAL_SEC = 180
locust.stats.HISTORY_STATS_INTERVAL_SEC = 60
locust.stats.CSV_STATS_INTERVAL_SEC = 60
locust.stats.CSV_STATS_FLUSH_INTERVAL_SEC = 60
locust.stats.CURRENT_RESPONSE_TIME_PERCENTILE_WINDOW = 60
locust.stats.PERCENTILES_TO_REPORT = [0.50, 0.90, 0.95, 0.99, 0.999, 1.0]

random.seed(time.time())
logging.basicConfig(level=logging.INFO)


def get_user():
    user_id = random.randint(0, 500)
    user_name = "Cornell_" + str(user_id)
    password = ""
    for i in range(0, 10):
        password = password + str(user_id)
    return user_name, password


mean_iat = 1  # seconds

request_log_file = open("request.log", "a")


@events.init_command_line_parser.add_listener
def _(parser):
    parser.add_argument(
        '--use-proxy',
        help="Use topfull proxy",
        default=False
    )

class SocialMediaUser(HttpUser):
    # return wait time in second
    def wait_time(self):
        global mean_iat
        return random.expovariate(lambd=1 / mean_iat)

    def on_start(self):
        if self.environment.parsed_options.use_proxy:
            self.client.proxies = {"http": "http://10.10.1.1:8090"}
            self.client.verify = False

        # Create UNIX socket once per user, with retry loop
        max_retries = 20
        retry_delay = 0.5  # seconds
        self.sock = None
        for attempt in range(1, max_retries + 1):
            try:
                self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self.sock.connect("/tmp/locust_log.sock")
                break
            except Exception as e:
                logging.warning(f"Attempt {attempt}: Failed to connect to UNIX socket: {e}")
                self.sock = None
                time.sleep(retry_delay)

        if self.sock is None:
            logging.error(f"Failed to connect to UNIX socket after {max_retries} attempts.")

    def on_stop(self):
        # Close UNIX socket on user stop
        if self.sock:
            try:
                self.sock.close()
            except Exception as e:
                logging.error(f"Failed to close UNIX socket: {e}")

    def log_request(self, response_time, context, exception=None):
        log_data = json.dumps({
            "time": time.time(),
            "latency": response_time,
            "context": context,
            "failed": "True" if exception else "False",
        }) + "\n"

        # Also log to local file for backup
        request_log_file.write(log_data)

        if self.sock:
            try:
                self.sock.sendall(log_data.encode())
            except Exception as e:
                logging.error(f"Failed to send log to UNIX socket: {e}")
        else:
            logging.error("No UNIX socket available for logging.")

    @task(600)
    def search_hotel(self):
        in_date = random.randint(9, 23)
        out_date = random.randint(in_date + 1, 24)

        if in_date <= 9:
            in_date = "2015-04-0" + str(in_date)
        else:
            in_date = "2015-04-" + str(in_date)

        if out_date <= 9:
            out_date = "2015-04-0" + str(out_date)
        else:
            out_date = "2015-04-" + str(out_date)

        lat = 38.0235 + (random.randint(0, 481) - 240.5) / 1000.0
        lon = -122.095 + (random.randint(0, 325) - 157.0) / 1000.0

        path = ("/hotels?inDate=" + in_date + "&outDate=" + out_date +
                "&lat=" + str(lat) + "&lon=" + str(lon))

        try:
            response = self.client.get(path, name="search", context={"type": "search"})
            response_time = response.elapsed.total_seconds() * 1000 if hasattr(response, 'elapsed') else None
            self.log_request(response_time, {"type": "search"})
        except Exception as e:
            self.log_request(None, {"type": "search"}, exception=e)

    @task(350)
    def recommend(self):
        coin = random.random()
        if coin < 0.33:
            req_param = "dis"
        elif coin < 0.66:
            req_param = "rate"
        else:
            req_param = "price"

        lat = 38.0235 + (random.randint(0, 481) - 240.5) / 1000.0
        lon = -122.095 + (random.randint(0, 325) - 157.0) / 1000.0

        path = ("/recommendations?require=" + req_param + "&lat=" + str(lat) +
                "&lon=" + str(lon))

        try:
            response = self.client.get(path, name="recommend", context={"type": "recommend"})
            response_time = response.elapsed.total_seconds() * 1000 if hasattr(response, 'elapsed') else None
            self.log_request(response_time, {"type": "recommend"})
        except Exception as e:
            self.log_request(None, {"type": "recommend"}, exception=e)

    @task(25)
    def reserve(self):
        in_date = random.randint(9, 23)
        out_date = in_date + random.randint(1, 5)

        if in_date <= 9:
            in_date = "2015-04-0" + str(in_date)
        else:
            in_date = "2015-04-" + str(in_date)

        if out_date <= 9:
            out_date = "2015-04-0" + str(out_date)
        else:
            out_date = "2015-04-" + str(out_date)

        lat = 38.0235 + (random.randint(0, 481) - 240.5) / 1000.0
        lon = -122.095 + (random.randint(0, 325) - 157.0) / 1000.0

        hotel_id = str(random.randint(1, 80))
        user_name, password = get_user()

        num_room = 1

        path = ("/reservation?inDate=" + in_date + "&outDate=" + out_date +
                "&lat=" + str(lat) + "&lon=" + str(lon) + "&hotelId=" +
                hotel_id + "&customerName=" + user_name + "&username=" +
                user_name + "&password=" + password + "&number=" +
                str(num_room))

        try:
            response = self.client.post(path, name="reserve", context={"type": "reserve"})
            response_time = response.elapsed.total_seconds() * 1000 if hasattr(response, 'elapsed') else None
            self.log_request(response_time, {"type": "reserve"})
        except Exception as e:
            self.log_request(None, {"type": "reserve"}, exception=e)

    @task(25)
    def user_login(self):
        user_name, password = get_user()
        path = "/user?username=" + user_name + "&password=" + password

        try:
            response = self.client.get(path, name="user", context={"type": "user"})
            response_time = response.elapsed.total_seconds() * 1000 if hasattr(response, 'elapsed') else None
            self.log_request(response_time, {"type": "user"})
        except Exception as e:
            self.log_request(None, {"type": "user"}, exception=e)


RPS = list(map(int, Path("rps.txt").read_text().splitlines()))


class CustomShape(LoadTestShape):
    print(RPS[:100])
    time_limit = len(RPS)
    spawn_rate = 100

    def tick(self):
        run_time = self.get_run_time()
        if run_time < self.time_limit:
            print(f"run_time: {run_time}, RPS: {RPS[int(run_time)]}")
            user_count = RPS[int(run_time)]
            return (user_count, self.spawn_rate)
        return None
