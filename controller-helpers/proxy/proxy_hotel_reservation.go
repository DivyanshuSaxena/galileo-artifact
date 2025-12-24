package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io/ioutil"
	"log"
	"net/http"
	"os"
	"os/signal"
	"os/user"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/elazarl/goproxy"

	"golang.org/x/time/rate"
)

var (
	limiter            = rate.NewLimiter(70, 70)
	limitDir           string
	limiterTable       = make(map[string]*rate.Limiter)
	global_config_path = os.Getenv("GLOBAL_CONFIG_PATH")
	global_config      Config
	mapStats           = make(map[string]*StatsModule)
	globalLock         *sync.Mutex
)

type Config struct {
	ProxyDir    string   `json:"proxy_dir"`
	FrontendUrl string   `json:"frontend_url"`
	TargetAPI   []string `json:"record_target"`
}

type StatsModule struct {
	numReq           map[int64]int64
	lastReqTimestamp int64
	startTimestamp   int64
	localLock        *sync.Mutex
}

func (stats *StatsModule) reset() {
	stats.numReq = make(map[int64]int64)
	stats.lastReqTimestamp = 0
	stats.startTimestamp = time.Now().Unix()
	stats.localLock = &sync.Mutex{}
}

func (stats *StatsModule) logRequest() {
	stats.localLock.Lock()
	defer stats.localLock.Unlock()
	currentTime := time.Now().Unix()
	num, ok := stats.numReq[currentTime]
	if !ok {
		stats.numReq[currentTime] = 1
	} else {
		stats.numReq[currentTime] = num + 1
	}
	stats.lastReqTimestamp = currentTime
}

func (stats *StatsModule) currentRPS() float64 {
	stats.localLock.Lock()
	defer stats.localLock.Unlock()
	if stats.lastReqTimestamp == 0 {
		return 0
	}
	var startTime int64
	currentTime := time.Now().Unix()
	if currentTime-4 > stats.startTimestamp {
		startTime = currentTime - 4
	} else {
		startTime = stats.startTimestamp
	}

	var total int64
	total = 0
	for t := startTime; t < currentTime; t++ {
		req, ok := stats.numReq[t]
		if !ok {
			total += 0
		} else {
			total += req
		}
	}
	if currentTime-startTime == 0 {
		return 0
	} else {
		return float64(total) / float64(currentTime-startTime)
	}
}

func init() {
	b, err := ioutil.ReadFile(global_config_path)
	if err != nil {
		fmt.Println(err)
	}
	json.Unmarshal(b, &global_config)

	usr, err := user.Current()
	if err != nil {
		log.Fatal(err)
	}
	homeDir := usr.HomeDir

	proxyDir := global_config.ProxyDir
	if strings.HasPrefix(proxyDir, "~/") {
		limitDir = filepath.Join(homeDir, proxyDir[2:])
	} else {
		limitDir = proxyDir
	}

	// Make limitDir if not exist
	if _, err := os.Stat(limitDir); os.IsNotExist(err) {
		os.Mkdir(limitDir, 0755)
	}

	for _, elem := range global_config.TargetAPI {
		limiterTable[elem] = rate.NewLimiter(10000, 10000)
		limiterTable[elem].SetBurst(10000)

		mapStats[elem] = &StatsModule{}
		mapStats[elem].reset()
	}

	globalLock = &sync.Mutex{}

}

func monitorRPS() {
	fmt.Printf("Start monitoring\n")
	for true {
		// Monitor every 5 seconds to reduce logging overhead and space.
		time.Sleep(5 * time.Second)
		fmt.Printf("-------------------------\n")
		for _, elem := range global_config.TargetAPI {
			fmt.Printf("%s: %.1f ", elem, mapStats[elem].currentRPS())
			fmt.Printf("\n")
		}
	}
}

func changeLimitDelta() {
	dir, err := ioutil.ReadDir(limitDir)
	if err != nil {
		return
	}
	for _, fInfo := range dir {
		api := fInfo.Name()
		apiFile := filepath.Join(limitDir, api)
		f, err := os.Open(apiFile)
		if err != nil {
			continue
		}
		defer f.Close()
		scanner := bufio.NewScanner(f)
		scanner.Scan()
		newRate, err := strconv.ParseFloat(scanner.Text(), 64)
		if err != nil {
			os.Remove(apiFile)
			continue
		}

		targetLimiter, ok := limiterTable[api]
		if !ok {
			println("Wrong API")
			os.Remove(apiFile)
			continue
		}
		currentRate := float64(targetLimiter.Limit())
		newRateFloat := newRate + currentRate
		if newRateFloat <= 0.0 {
			println("Too low threshold")
			os.Remove(apiFile)
			continue
		}

		targetLimiter.SetLimit(rate.Limit(newRateFloat))
		targetLimiter.SetBurst(int(newRateFloat))
		println("Apply threshold to ", api, " : ", int(newRateFloat))
		os.Remove(apiFile)
	}
}

func changeLimitAbs() {
	dir, err := ioutil.ReadDir(limitDir)
	if err != nil {
		println("Cannot read dir")
		return
	}
	for _, fInfo := range dir {
		api := fInfo.Name()
		apiFile := filepath.Join(limitDir, api)
		f, err := os.Open(apiFile)
		if err != nil {
			println("Cannot open " + api)
			continue
		}
		defer f.Close()
		scanner := bufio.NewScanner(f)
		scanner.Scan()
		newRate, err := strconv.ParseFloat(scanner.Text(), 64)
		if err != nil {
			os.Remove(apiFile)
			print("Wrong rate")
			continue
		}

		targetLimiter, ok := limiterTable[api]
		if !ok {
			println("Wrong API")
			os.Remove(apiFile)
			continue
		}

		targetLimiter.SetLimit(rate.Limit(float64(newRate)))
		targetLimiter.SetBurst(int(newRate))
		println("Apply threshold to ", api, " : ", int(newRate))
		os.Remove(apiFile)
	}
}

func RejectUser(r *http.Request, ctx *goproxy.ProxyCtx) (*http.Request, *http.Response) {
	mapStats["user"].logRequest()
	if limiterTable["user"].Allow() == false {
		return r, goproxy.NewResponse(r, goproxy.ContentTypeText, http.StatusForbidden, "REJECT!")
	} else {
		return r, nil
	}
}
func RejectSearch(r *http.Request, ctx *goproxy.ProxyCtx) (*http.Request, *http.Response) {
	mapStats["search"].logRequest()
	if limiterTable["search"].Allow() == false {
		return r, goproxy.NewResponse(r, goproxy.ContentTypeText, http.StatusForbidden, "REJECT!")
	} else {
		return r, nil
	}
}
func RejectRecommend(r *http.Request, ctx *goproxy.ProxyCtx) (*http.Request, *http.Response) {
	mapStats["recommend"].logRequest()
	if limiterTable["recommend"].Allow() == false {
		return r, goproxy.NewResponse(r, goproxy.ContentTypeText, http.StatusForbidden, "REJECT!")
	} else {
		return r, nil
	}
}
func RejectReserve(r *http.Request, ctx *goproxy.ProxyCtx) (*http.Request, *http.Response) {
	mapStats["reserve"].logRequest()
	if limiterTable["reserve"].Allow() == false {
		return r, goproxy.NewResponse(r, goproxy.ContentTypeText, http.StatusForbidden, "REJECT!")
	} else {
		return r, nil
	}
}

func ReqStat(r *http.Request, ctx *goproxy.ProxyCtx) (*http.Request, *http.Response) {
	target_apis := global_config.TargetAPI
	out := ""
	for _, elem := range target_apis {
		out += fmt.Sprintf("%s=%1.f/", elem, mapStats[elem].currentRPS())
	}

	return r, goproxy.NewResponse(r, goproxy.ContentTypeText, http.StatusOK, out)

}

func ReqThreshold(r *http.Request, ctx *goproxy.ProxyCtx) (*http.Request, *http.Response) {
	out := ""
	apis := global_config.TargetAPI
	for _, elem := range apis {
		out += fmt.Sprintf("%s=%.1f/", elem, float64(limiterTable[elem].Limit()))
	}
	return r, goproxy.NewResponse(r, goproxy.ContentTypeText, http.StatusOK, out)
}

var GetUserCondition goproxy.ReqConditionFunc = func(req *http.Request, ctx *goproxy.ProxyCtx) bool {
	return req.URL.Host == global_config.FrontendUrl &&
		req.Method == "GET" &&
		strings.Contains(req.URL.Path, "/user")
}
var GetSearchCondition goproxy.ReqConditionFunc = func(req *http.Request, ctx *goproxy.ProxyCtx) bool {
	return req.URL.Host == global_config.FrontendUrl &&
		req.Method == "GET" &&
		strings.Contains(req.URL.Path, "/hotels")
}
var GetRecommendCondition goproxy.ReqConditionFunc = func(req *http.Request, ctx *goproxy.ProxyCtx) bool {
	return req.URL.Host == global_config.FrontendUrl &&
		req.Method == "GET" &&
		strings.Contains(req.URL.Path, "/recommendations")
}
var PostReserveCondition goproxy.ReqConditionFunc = func(req *http.Request, ctx *goproxy.ProxyCtx) bool {
	return req.URL.Host == global_config.FrontendUrl &&
		req.Method == "POST" &&
		req.URL.Path == "/reservation"
}

var ReqStatCondition goproxy.ReqConditionFunc = func(req *http.Request, ctx *goproxy.ProxyCtx) bool {
	return req.Method == "GET" &&
		strings.Contains(req.URL.Path, "/stats")
}
var ReqThresholdCondition goproxy.ReqConditionFunc = func(req *http.Request, ctx *goproxy.ProxyCtx) bool {
	return req.Method == "GET" &&
		strings.Contains(req.URL.Path, "/thresholds")
}

func main() {
	sigs := make(chan os.Signal, 1)
	signal.Notify(sigs, syscall.SIGUSR1)
	go func() {
		for {
			sig := <-sigs
			println("Get signal", sig)
			changeLimitAbs()
		}
	}()

	go monitorRPS()

	proxy := goproxy.NewProxyHttpServer()
	proxy.Verbose = false
	proxy.Tr.MaxIdleConns = 50000
	proxy.Tr.MaxIdleConnsPerHost = 50000

	proxy.OnRequest(GetUserCondition).DoFunc(RejectUser)
	proxy.OnRequest(GetSearchCondition).DoFunc(RejectSearch)
	proxy.OnRequest(GetRecommendCondition).DoFunc(RejectRecommend)
	proxy.OnRequest(PostReserveCondition).DoFunc(RejectReserve)

	proxy.OnRequest(ReqStatCondition).DoFunc(ReqStat)
	proxy.OnRequest(ReqThresholdCondition).DoFunc(ReqThreshold)
	println("Start")
	log.Fatal(http.ListenAndServe(":8090", proxy))
}
