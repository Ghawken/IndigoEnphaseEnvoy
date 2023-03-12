#! /usr/bin/env python2.6
# -*- coding: utf-8 -*-

"""
Enphase Indigo Plugin
Authors: GlennNZ

Enphase Plugin

"""

import json
import sys
import time as t
import requests
try:
    # For Python 3.0 and later
    from urllib.request import urlopen
except ImportError:
    # Fall back to Python 2's urllib2
    from urllib2 import urlopen
import os
import shutil
import flatdict
import re
import logging
import datetime
import threading
from requests.auth import HTTPDigestAuth

try:
    import indigo
except:
    pass

# Establish default plugin prefs; create them if they don't already exist.
kDefaultPluginPrefs = {
    u'configMenuPollInterval': "300",  # Frequency of refreshes.
    u'configMenuServerTimeout': "15",  # Server timeout limit.
    # u'refreshFreq': 300,  # Device-specific update frequency
    u'showDebugInfo': False,  # Verbose debug logging?
    u'configUpdaterForceUpdate': False,
    u'configUpdaterInterval': 24,
    u'showDebugLevel': "1",  # Low, Medium or High debug output.
    u'updaterEmail': "",  # Email to notify of plugin updates.
    u'updaterEmailsEnabled': False  # Notification of plugin updates wanted.
}
PRODUCTION_REGEX = \
    r'<td>Currentl.*</td>\s+<td>\s*(\d+|\d+\.\d+)\s*(W|kW|MW)</td>'
DAY_PRODUCTION_REGEX = \
    r'<td>Today</td>\s+<td>\s*(\d+|\d+\.\d+)\s*(Wh|kWh|MWh)</td>'
WEEK_PRODUCTION_REGEX = \
    r'<td>Past Week</td>\s+<td>\s*(\d+|\d+\.\d+)\s*(Wh|kWh|MWh)</td>'
LIFE_PRODUCTION_REGEX = \
    r'<td>Since Installation</td>\s+<td>\s*(\d+|\d+\.\d+)\s*(Wh|kWh|MWh)</td>'

class Plugin(indigo.PluginBase):
    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        indigo.PluginBase.__init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs)
        self.debugLog(u"Initializing Enphase plugin.")

        self.timeOutCount = 0
        self.debug = self.pluginPrefs.get('showDebugInfo', False)
        self.debugLevel = self.pluginPrefs.get('showDebugLevel', "1")
        self.deviceNeedsUpdated = ''
        self.prefServerTimeout = int(self.pluginPrefs.get('configMenuServerTimeout', "15"))
        self.https_flag = ""
        self.configUpdaterInterval = self.pluginPrefs.get('configUpdaterInterval', 24)
        self.configUpdaterForceUpdate = self.pluginPrefs.get('configUpdaterForceUpdate', False)
        self.debugupdate = self.pluginPrefs.get('debugupdate', False)
        self.openStore = self.pluginPrefs.get('openStore', False)
        self.WaitInterval = 0
        self.endpoint_type = ""
        self.endpoint_url = ""
        self.serial_number_last_six = ""
        self.EnvoyStype = ""
        self.logger.info(u"")
        self.logger.info(u"{0:=^130}".format(" Initializing New Plugin Session "))
        self.logger.info(u"{0:<30} {1}".format("Plugin name:", pluginDisplayName))
        self.logger.info(u"{0:<30} {1}".format("Plugin version:", pluginVersion))
        self.logger.info(u"{0:<30} {1}".format("Plugin ID:", pluginId))
        self.logger.info(u"{0:<30} {1}".format("Indigo version:", indigo.server.version))
        self.logger.info(u"{0:<30} {1}".format("Python version:", sys.version.replace('\n', '')))
        self.logger.info(u"{0:<30} {1}".format("Python Directory:", sys.prefix.replace('\n', '')))
        self.logger.info(u"{0:=^130}".format(" End Initializing New Plugin Session "))

        # Convert old debugLevel scale to new scale if needed.
        # =============================================================
        if not isinstance(self.pluginPrefs['showDebugLevel'], int):
            if self.pluginPrefs['showDebugLevel'] == "High":
                self.pluginPrefs['showDebugLevel'] = 3
            elif self.pluginPrefs['showDebugLevel'] == "Medium":
                self.pluginPrefs['showDebugLevel'] = 2
            else:
                self.pluginPrefs['showDebugLevel'] = 1

    def __del__(self):
        if self.debugLevel >= 2:
            self.debugLog(u"__del__ method called.")
        indigo.PluginBase.__del__(self)

    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        if self.debugLevel >= 2:
            self.debugLog(u"closedPrefsConfigUi() method called.")

        if userCancelled:
            self.debugLog(u"User prefs dialog cancelled.")

        if not userCancelled:
            self.debug = valuesDict.get('showDebugInfo', False)
            self.debugLevel = self.pluginPrefs.get('showDebugLevel', "1")
            self.debugLog(u"User prefs saved.")
            self.debugupdate = valuesDict.get('debugupdate', False)
            self.openStore = valuesDict.get('openStore', False)

            if self.debug:
                indigo.server.log(u"Debugging on (Level: {0})".format(self.debugLevel))
            else:
                indigo.server.log(u"Debugging off.")

            if int(self.pluginPrefs['showDebugLevel']) >= 3:
                self.debugLog(u"valuesDict: {0} ".format(valuesDict))

        return True

    # Start 'em up.
    def deviceStartComm(self, dev):
        if self.debugLevel >= 2:
            self.debugLog(u"deviceStartComm() method called.")
        #self.errorLog(str(dev.model))

        # CHECK IF PANEL - IF PANEL START OFFLINE
        # IF ENVOY START ONLINE
        if dev.model=='Enphase Panel':
            #self.errorLog(' Enphase Panel')
            #dev.updateStateOnServer('deviceIsOnline', value=False, uiValue="Offline")
            #dev.updateStateImageOnServer(indigo.kStateImageSel.Auto)
            #dev.updateStateOnServer('watts', value=0)
            dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)
            dev.stateListOrDisplayStateIdChanged()
            return
        #number_Panels = 0
        #numer_Panels = indigo.devices.len(filter='self.EnphasePanelDevice')
        indigo.server.log(u"Starting Enphase/Envoy device: " + dev.name )
        dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)
        dev.updateStateOnServer('deviceIsOnline', value=True, uiValue="Online")

        dev.stateListOrDisplayStateIdChanged()


# Default Indigo Plugin StateList
# This overrides and pulls the current state list (from devices.xml and then adds whatever to it via these calls
# http://forums.indigodomo.com/viewtopic.php?f=108&t=12898
# for summary
# Issue being that with trigger and control page changes will add the same to all devices unless check what device within below call - should be an issue for this plugin
# """"
#     def getDeviceStateList(self,dev):
#         if self.debugLevel>=2:
#             self.debugLog(u'getDeviceStateList called')
#
#         stateList = indigo.PluginBase.getDeviceStateList(self, dev)
#         if stateList is not None:
#             # Add any dynamic states onto the device based on the node's characteristics.
#                 someNumState = self.getDeviceStateDictForNumberType(u"someNumState", u"Some Level Label",
#                                                                     u"Some Level Label")
#                 someStringState = self.getDeviceStateDictForStringType(u"someStringState", u"Some Level Label",
#                                                                        u"Some Level Label")
#                 someOnOffBoolState = self.getDeviceStateDictForBoolOnOffType(u"someOnOffBoolState", u"Some Level Label",
#                                                                              u"Some Level Label")
#                 someYesNoBoolState = self.getDeviceStateDictForBoolYesNoType(u"someYesNoBoolState", u"Some Level Label",
#                                                                              u"Some Level Label")
#                 someOneZeroBoolState = self.getDeviceStateDictForBoolOneZeroType(u"someOneZeroBoolState",
#                                                                                  u"Some Level Label",
#                                                                                  u"Some Level Label")
#                 someTrueFalseBoolState = self.getDeviceStateDictForBoolTrueFalseType(u"someTrueFalseBoolState",
#                                                                                      u"Some Level Label",
#                                                                                      u"Some Level Label")
#                 stateList.append(someNumState)
#                 stateList.append(someStringState)
#                 stateList.append(someOnOffBoolState)
#                 stateList.append(someYesNoBoolState)
#                 stateList.append(someOneZeroBoolState)
#                 stateList.append(someTrueFalseBoolState)
#                 try:
#
#                     if self.PanelDict is not None:
#                         x=0
#                         for array in self.PanelDict:
#                             numberArray = "Panel"+str(x)
#                             Statearray = self.getDeviceStateDictForNumberType(numberArray,numberArray,numberArray)
#                             stateList.append(Statearray)
#                             x=x+1
#                 except Exception as error:
#                     self.errorLog(str('error in statelist Panel:'+error.message))
#         return stateList
# """"


    # Shut 'em down.
    def deviceStopComm(self, dev):
        if self.debugLevel >= 2:
            self.debugLog(u"deviceStopComm() method called.")
        indigo.server.log(u"Stopping Enphase device: " + dev.name + " and id:"+str(dev.model))
        dev.updateStateOnServer('deviceIsOnline', value=False, uiValue="Disabled")
        if dev.model == 'Enphase Envoy-S' :
            dev.updateStateOnServer('powerStatus', value='offline', uiValue='Offline')
            dev.updateStateOnServer('generatingPower', value=False)
            dev.updateStateOnServer('numberInverters', value=0)
            dev.updateStateOnServer('productionWattsNow', value=0)
            dev.updateStateOnServer('consumptionWattsNow', value=0)
            dev.updateStateOnServer('netConsumptionWattsNow', value=0)
            dev.updateStateOnServer('production7days', value=0)
            dev.updateStateOnServer('consumption7days', value=0)
            dev.updateStateOnServer('consumptionWattsToday', value=0)
            dev.updateStateOnServer('productionWattsToday', value=0)
            dev.updateStateOnServer('storageActiveCount', value=0)
            dev.updateStateOnServer('storageWattsNow', value=0)
            dev.updateStateOnServer('storageState', value='Offline')
            dev.updateStateOnServer('storagePercentFull', value=0)
            dev.updateStateOnServer('typeEnvoy', value="unknown")
            dev.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)
        if dev.model == 'Enphase Panel':
            dev.updateStateOnServer('watts', value=0)
            #dev.updateStateOnServer('serialNo', value=0)
            dev.updateStateOnServer('maxWatts', value=0)
            dev.updateStateOnServer('deviceIsOnline', value=False, uiValue="Offline")
            dev.updateStateOnServer('status', value='')
            dev.updateStateOnServer('modelNo', value='')
            dev.updateStateOnServer('producing', value=False)
            dev.updateStateOnServer('communicating', value=False)
            dev.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)
        if dev.model== 'Enphase Legacy':
            dev.updateStateOnServer('wattHoursLifetime', value=0)
            dev.updateStateOnServer('wattHoursSevenDays', value=0)
            dev.updateStateOnServer('wattHoursToday', value=0)
            dev.updateStateOnServer('wattsNow', value=0)
            dev.updateStateOnServer('powerStatus', value='offline', uiValue='Offline')
    def forceUpdate(self):
        self.updater.update(currentVersion='0.0.0')

    def pluginstoreUpdate(self):
        iurl = 'http://www.indigodomo.com/pluginstore/105/'
        self.browserOpen(iurl)

    def refreshDatafromMenu(self):
        indigo.server.log(u'Manually Refreshing Enphase Data:')
        for dev in indigo.devices.iter('self.EnphaseEnvoyDevice'):
            if self.debugLevel >= 2:
                self.debugLog(u'Quick Checks Before Loop')
            if dev.enabled:
                self.refreshDataForDev(dev)
                self.sleep(30)
                self.checkPanelInventory(dev)
                self.sleep(30)
                self.checkThePanels_New(dev)
                self.sleep(10)
        return



    def check_endpoints(self, valuesDict, typeId, devId):
        self.logger.info("Checking endpoints.")
        end_thread = threading.Thread(target=self.thread_endpoints, args=[valuesDict, typeId, devId])
        end_thread.start()


    def thread_endpoints(self, valuesDict, typeId, devId):
       # delete all panel devices first up
        self.logger.info(f"Checking all possible Endpoints...")
        self.logger.info(f"Pausing usual updates for 3 minutes")
        #self.logger.debug(f"valueDict {valuesDict}")
        dev = indigo.devices[devId]
        sourceip = valuesDict["sourceXML"]
        self.WaitInterval = 360
        endpoints = [ "http{}://{}/production.json",
                      "http{}://{}/production",
                      "http{}://{}/inventory.json",
                      "http{}://{}/api/v1/production",
                      "http{}://{}/api/v1/production/inverters",
                      "http{}://{}/auth/check_jwt",
                      "http{}://{}/ivp/meters",
                      "http{}://{}/ivp/meters/readings","http{}://{}/ivp/livedata/status",
                      "http{}://{}/ivp/meters/reports/consumption",
                      "http{}://{}/info.xml"
                      ]
        success = []
        https_flag = "s"
        for endpoint in endpoints:
            url = endpoint.format(https_flag, sourceip)
            try:
                self.sleep(2)
                self.logger.debug(f"Trying Endpoint:{url}")
                headers = self.create_headers(dev)
                response = requests.get(url, timeout=25, headers=headers, allow_redirects=False)
                if response.status_code == 200:
                    self.logger.info(f"Success:  {url}")
                    self.logger.info(f"Response: {response.json()}")
                else:
                    self.logger.debug(f"Failed, Response Code  {response.status_code}")
                    self.logger.debug(f"Response: {response}")
            except Exception as ex:
                self.logger.debug(f"Failed.  Exception: {ex}")
            self.logger.debug("---------------------------------")
        https_flag = ""
        for endpoint in endpoints:
            url = endpoint.format(https_flag, sourceip)
            try:
                self.sleep(2)
                self.logger.debug(f"Trying Endpoint:{url}")
                headers = self.create_headers(dev)
                response = requests.get(url, timeout=25, headers=headers, allow_redirects=False)
                if response.status_code == 200:
                    self.logger.info(f"Success:  {url}")
                    self.logger.info(f"Response: {response.json()}")
                else:
                    self.logger.debug(f"Failed, Response Code  {response.status_code}")
                    self.logger.debug(f"Response: {response}")
            except Exception as ex:
                self.logger.debug(f"Failed.  Exception: {ex}")

        self.logger.info(" ------- End of Check Endpoints -------")
        self.WaitInterval = 0


        return

    def runConcurrentThread(self):

        try:
            panellastcheck = t.time()
            envoyslastcheck = t.time()
            envoylegacylastcheck = t.time()
            panelinventorylastcheck = t.time()
            Anychecklastcheck = t.time()
            checkEnvoyType = t.time()
            checkdateTime = t.time()
## check main device on startup.
            for dev in indigo.devices.iter('self.EnphaseEnvoyDevice'):
                if self.debugLevel>=2:
                    self.debugLog(u'Quick Checks Before Loop')
                if dev.enabled:
                    self.refreshDataForDev(dev)
                    self.sleep(15)
            for dev in indigo.devices.iter('self.EnphaseEnvoyLegacy'):
                if dev.enabled :
                    self.legacyRefreshEnvoy(dev)
                    self.sleep(15)

# Loop for continuing checks
            while True:
                for dev in indigo.devices.iter('self.EnphaseEnvoyDevice'):
                    if dev.enabled and t.time() > (checkdateTime+ 1320):  ##22 minutes --
                        ## Checking current time/date
                        self.checkDayTime(dev)
                        checkdateTime = t.time()

                    if dev.enabled and t.time() > (checkEnvoyType + 21600 ): ## 6 hours
                        self.checkEnvoyType(dev)
                        checkEnvoyType = t.time()
                    elif dev.enabled and t.time() > (panelinventorylastcheck + 300):   # minutes
                        self.checkPanelInventory(dev)
                        self.sleep(5)
                        panelinventorylastcheck = t.time()
                    elif dev.enabled and t.time() > (panellastcheck + 200):  # minutes
                        self.checkThePanels_New(dev)
                        panellastcheck = t.time()
                        self.sleep(5)
                    elif dev.enabled and t.time() > (envoyslastcheck + 60):  # 2minutes
                        self.refreshDataForDev(dev)
                        envoyslastcheck = t.time()
                        self.sleep(5)
                for dev in indigo.devices.iter('self.EnphaseEnvoyLegacy'):
                    if dev.enabled and t.time()>(envoylegacylastcheck+60):
                        self.legacyRefreshEnvoy(dev)
                        self.sleep(5)
                        envoylegacylastcheck = t.time()

                self.sleep(25)
                if self.WaitInterval>0:
                    self.WaitInterval = 0
                    self.sleep(120)
                    envoyslastcheck = t.time()
                    envoylegacylastcheck = t.time()
                    panelinventorylastcheck = t.time()
                    panellastcheck = t.time()

        except self.StopThread:
            self.debugLog(u'Restarting/or error. Stopping Enphase/Envoy thread.')
            pass

        except Exception:
            self.logger.exception(u"Exception in Main Loop")
            self.WaitInterval = 60
            pass

    def checkDayTime(self, device):
        try:
            today = datetime.datetime.today()

            if today.timetz().hour == 0:  ## midnight
                device.updateStateOnServer('productionWattsMaxToday', value=int(0))
                if today.isoweekday()==7: ## Its Sunday...
                    device.updateStateOnServer('productionWattsMaxWeek', value=int(0))

        except:
            self.logger.exception("Caught Exception")

    def shutdown(self):
        if self.debugLevel >= 2:
            self.debugLog(u"shutdown() method called.")

    def startup(self):
        if self.debugLevel >= 2:
            self.debugLog(u"Starting Enphase Plugin. startup() method called.")

        # See if there is a plugin update and whether the user wants to be notified.

    def validatePrefsConfigUi(self, valuesDict):
        if self.debugLevel >= 2:
            self.debugLog(u"validatePrefsConfigUi() method called.")

        error_msg_dict = indigo.Dict()

        # self.errorLog(u"Plugin configuration error: ")

        return True, valuesDict

####  new all model changes
    def hasProductionAndConsumption(self, json):
        """Check if json has keys for both production and consumption"""
        return "production" in json and "consumption" in json

    def create_headers(self,  dev):
        self.logger.debug(f"Create_Headers called for device.name {dev.name} ")
        headers = {}
        use_token = dev.pluginProps.get('use_token', False)
        auth_token = dev.pluginProps.get('auth_token', "")
        self.logger.debug(f"Use_token: {use_token}")
        if use_token and auth_token !="":
            headers = {"Accept": "application/json", "Authorization": "Bearer "+auth_token}
            if self.debug:
                self.logger.debug(f"Using Headers: {headers}")
            self.https_flag = "s"
            return headers
        else:
            self.https_flag =""
            return {}


    def detect_model(self, dev):
        """Method to determine if the Envoy supports consumption values or
         only production"""
        self.endpoint_url = f"http{self.https_flag}://{dev.pluginProps['sourceXML']}/production.json"
        self.logger.debug("trying Endpoint:"+str(self.endpoint_url))
        headers =  self.create_headers(dev)
        self.endpoint_url = f"http{self.https_flag}://{dev.pluginProps['sourceXML']}/production.json"
        response = requests.get(  self.endpoint_url, timeout=15, headers={},allow_redirects=False)
        if response.status_code == 200 and self.hasProductionAndConsumption(response.json()):
            # Okay - this is Envoy S or Envoy-S Metered
            # Some have lots of blanks, need a new device type
            # CHange of plans - leave here for Legacy support, add check for EnvoyS types within this device type
            self.endpoint_type = "PC"
            self.logger.info("Success with EndPoint: " + str(self.endpoint_url))
            self.logger.info(f"Response\n:{response}")
            return True
        else:
            self.endpoint_url = f"http{self.https_flag}://{dev.pluginProps['sourceXML']}/api/v1/production"
            self.logger.debug("trying Endpoint:" + str(self.endpoint_url))
            headers = self.create_headers( dev)
            self.endpoint_url = f"http{self.https_flag}://{dev.pluginProps['sourceXML']}/api/v1/production"
            response = requests.get(  self.endpoint_url, timeout=15, headers=headers,allow_redirects=False)
            if response.status_code == 200:
                self.endpoint_type = "P"       # Envoy-C, production only
                self.logger.info("Success with EndPoint: "+ str(self.endpoint_url))
                self.logger.info(f"Response\n:{response}")
                return True
            else:
                self.endpoint_url = "http://{}/production".format(dev.pluginProps['sourceXML'])
                self.logger.debug("trying Endpoint:" + str(self.endpoint_url))
                headers = self.create_headers( dev)
                response = requests.get(  self.endpoint_url, timeout=15, headers=headers, allow_redirects=False)
                if response.status_code == 200:
                    self.endpoint_type = "P0"       # older Envoy-C
                    self.logger.debug("Success with EndPoint: " + str(self.endpoint_url))
                    return True

        self.endpoint_url = ""
        self.logger.info(
            "Could not connect or determine Envoy model. " +
            "Check that the device is up at 'http://" + self.host + "'.")
        return False

    def call_api(self, dev):
        """Method to call the Envoy API"""
        # detection of endpoint if not already known
        try:
            if self.endpoint_type == "":
                self.detect_model()
            response =  requests.get(self.endpoint_url, timeout=15, allow_redirects=False)
            if self.endpoint_type == "P" or self.endpoint_type == "PC":
                return response.json()  # these Envoys have .json
            if self.endpoint_type == "P0":
                return response.text  # these Envoys have .html

        except requests.Timeout:
            self.logger.debug("Requests Timeout for :"+str(self.endpoint_url))
            self.WaitInterval =60
            result = None
            return result
        except Exception as ex:
            self.logger.debug("Error Calling Endpoint:"+str(ex))
            dev.updateStateOnServer('deviceIsOnline', value=False, uiValue="Offline")
            dev.updateStateOnServer('powerStatus', value = 'offline')
            dev.setErrorStateOnServer(u'Offline')
            result = None
            return result

    def getTheDataAllModels(self,dev):
        if self.debugLevel >= 2:
            self.debugLog(u"getTheDataAll Models method called.")
        self.logger.debug("Checking Model & getting data of dev.id" + str(dev.name))

        if self.endpoint_type == "":
            if self.detect_model(dev):
                dev.updateStateOnServer('deviceIsOnline', value=True, uiValue="Online")
                dev.setErrorStateOnServer(None)
                self.WaitInterval = 0
            else:
                self.WaitInterval = 60
                if self.debugLevel >= 2:
                    self.debugLog(u"Device is offline. No data to return. ")
                dev.updateStateOnServer('deviceIsOnline', value=False, uiValue="Offline")
                dev.updateStateOnServer('powerStatus', value='offline')
                dev.setErrorStateOnServer(u'Offline')
                return

        allData = self.call_api(dev)
        self.logger.debug(str(allData))

        self.processAllData(dev,allData)

    def processAllData(self,dev,allData):
        self.logger.debug("Process all data received called: Data:"+str(allData))

        try:

            daily_production = float(0)
            lifetime_production = float(0)
            production = float(0)
            consumption = float(0)
            daily_consumption = float(0)
            lifetime_consumption = float(0)
            seven_days_consumption = float(0)
            seven_days_production = float(0)

            ## Daily Production
            if self.endpoint_type == "PC":
                daily_production = float(allData["production"][1]["whToday"])
            else:
                if self.endpoint_type == "P":
                    daily_production = float(allData["wattHoursToday"])
                else:
                    if self.endpoint_type == "P0":
                        match = re.search(DAY_PRODUCTION_REGEX, allData, re.MULTILINE)
                        if match:
                            if match.group(2) == "kWh":
                                daily_production = float( match.group(1)) * 1000
                            else:
                                if match.group(2) == "MWh":
                                    daily_production = float( match.group(1)) * 1000000
                                else:
                                    daily_production = float( match.group(1))
                        else:
                            self.logger.debug (  "No match for Day production, check REGEX  " + allData)

            ## Current Production
            if self.endpoint_type == "PC":
                try:
                    production = float(allData["production"][1]["wNow"])
                except IndexError:
                    production = float(allData["production"][0]["wNow"])
            else:
                if self.endpoint_type == "P":
                    production = float(allData["wattsNow"])
                else:
                    if self.endpoint_type == "P0":
                        match = re.search( PRODUCTION_REGEX, allData, re.MULTILINE)
                        if match:
                            if match.group(2) == "kW":
                                production = float(match.group(1))*1000
                            else:
                                if match.group(2) == "mW":
                                    production = float( match.group(1))*1000000
                                else:
                                    production = float(match.group(1))
                        else:
                            self.logger.debug(
                                "No match for production, check REGEX  "
                                + allData)
            ## Daily Consumption, Lifetime
            if self.endpoint_type == "P" or self.endpoint_type == "P0":
                self.logger.debug("Consumption data not available:")
                consumption = float(0)
                daily_consumption = float(0)
                lifetime_consumption = float(0)
                seven_days_consumption = float(0)
            elif 'consumption' in allData and self.endpoint_type=="PC":  ## add another check
                daily_consumption = float(allData["consumption"][0]["whToday"])
                lifetime_consumption = float(allData["consumption"][0]["whLifetime"])
                seven_days_consumption = float(allData["consumption"][0]["whLastSevenDays"])
                consumption = float(allData["consumption"][0]["wNow"])

            # Lifetime Production
            if self.endpoint_type == "PC":
                lifetime_production = float(allData["production"][1]["whLifetime"])
            else:
                if self.endpoint_type == "P":
                    lifetime_production = float(allData["wattHoursLifetime"])
                else:
                    if self.endpoint_type == "P0":
                        match = re.search(
                            LIFE_PRODUCTION_REGEX, allData, re.MULTILINE)
                        if match:
                            if match.group(2) == "kWh":
                                lifetime_production = float(
                                    match.group(1))*1000
                            else:
                                if match.group(2) == "MWh":
                                    lifetime_production = float(
                                        match.group(1))*1000000
                                else:
                                    lifetime_production = float(
                                        match.group(1))
                        else:
                            self.logger.debug("No Lifetime production result, check Regex:"+str(allData))
            # Seven Days Consumption

            if self.endpoint_type == "PC":
                seven_days_production = float(allData["production"][1]["whLastSevenDays"])
            else:
                if self.endpoint_type == "P":
                    seven_days_production = float(allData["wattHoursSevenDays"])
                else:
                    if self.endpoint_type == "P0":
                        match = re.search(
                            WEEK_PRODUCTION_REGEX, allData, re.MULTILINE)
                        if match:
                            if match.group(2) == "kWh":
                                seven_days_production = float(
                                    match.group(1))*1000
                            else:
                                if match.group(2) == "MWh":
                                    seven_days_production = float(
                                        match.group(1))*1000000
                                else:
                                    seven_days_production = float(
                                        match.group(1))
                        else:
                            self.logger.debug("Error collecting 7 Days Production Data")

            devStateList = [
                {'key': 'consumptionWattsNow', 'value': consumption},
                {'key': 'consumption7days', 'value': seven_days_consumption},
                {'key': 'consumptionwhLifetime', 'value': lifetime_consumption},
                {'key': 'consumptionWattsToday', 'value': daily_consumption},
                {'key': 'productionWattsNow', 'value': production},
                {'key': 'productionwhLifetime', 'value': lifetime_production},
                {'key': 'production7days', 'value': seven_days_production},
                {'key': 'productionWattsToday', 'value': daily_production}
                ]

            dev.updateStatesOnServer(devStateList)


        except requests.exceptions.ConnectionError:
            self.logger.debug("Connection Error")
        except (json.decoder.JSONDecodeError, KeyError, IndexError):
            self.logger.exception("Json Error")

    def get_serial_number(self,dev):
        """Method to get last six digits of Envoy serial number for auth"""
        self.logger.debug("Get_Serial_Number_called. ")

        serial_num = dev.pluginProps.get("serial_number", "")
        if serial_num == "":
            self.logger.info("Serial Number not entered in device.  Attempt to find..")
            try:
                url = f"http{self.https_flag}://{dev.pluginProps['sourceXML']}/info.xml"
                headers = self.create_headers( dev)
                url = f"http{self.https_flag}://{dev.pluginProps['sourceXML']}/info.xml"
                response = requests.get( url, timeout=30, headers=headers, allow_redirects=False)
                if len(response.text) > 0:
                    sn = response.text.split("<sn>")[1].split("</sn>")[0][-6:]
                    self.serial_number_last_six = sn
                    self.logger.debug("Found Serial Number:"+str(self.serial_number_last_six))
                    return True
            except requests.exceptions.ConnectionError:
                self.logger.info("Error connecting to info.xml to find Serial Number")
                return False
        else:
            self.logger.info("Using Serial Number entered manually in device settings.")
            self.serial_number_last_six = serial_num[-6:]
            return serial_num[-6:]

    def gettheDataChoice(self,dev):
        envoyType= dev.states["typeEnvoy"]
        if envoyType == "Metered":
            return self.getTheData(dev)
        elif envoyType =="Unmetered":
            return self.legacyGetTheData(dev)
        else:
            self.logger.debug("Awaiting Envoy Type")
            return None

    def getTheData(self, dev):
        """
        The getTheData() method is used to retrieve  API Client Data
        """
        if self.debugLevel >= 2:
            self.debugLog(u"getTheData PRODUCTION METHOD method called.")

        try:
            url = f"http{self.https_flag}://{dev.pluginProps['sourceXML']}/production.json"
            headers = self.create_headers( dev)
            url = f"http{self.https_flag}://{dev.pluginProps['sourceXML']}/production.json"
            r = requests.get(url, timeout=35, headers=headers, allow_redirects=False)
            result = r.json()
            if self.debugLevel >= 2:
                self.debugLog(f"Result:{result}")

            dev.updateStateOnServer('deviceIsOnline', value=True, uiValue="Online")
            dev.setErrorStateOnServer(None)
            self.WaitInterval = 0
            return result

        except Exception as error:

            indigo.server.log(u"Error connecting to Device:" + str(dev.name) +" Error is:"+str(error))
            self.WaitInterval = 60
            if self.debugLevel >= 2:
                self.logger.debug(u"Device is offline. No data to return. ", exc_info=True)
            dev.updateStateOnServer('deviceIsOnline', value=False, uiValue="Offline")
            dev.updateStateOnServer('powerStatus', value = 'offline')
            dev.setErrorStateOnServer(u'Offline')
            result = None
            return result

    def legacyGetTheData(self, dev):
        """
        The getTheData() method is used to retrieve  API Client Data
        """
        if self.debugLevel >= 2:
            self.debugLog(u"getTheData PRODUCTION METHOD method called.")

        try:
            url = f"http{self.https_flag}://{dev.pluginProps['sourceXML']}/api/v1/production"
            headers = self.create_headers(dev)
            url = f"http{self.https_flag}://{dev.pluginProps['sourceXML']}/api/v1/production"
            r = requests.get(url,timeout=15 ,headers=headers, allow_redirects=False)
            result = r.json()
            if self.debugLevel >= 2:
                self.debugLog(u"Result:" + str(result))
            dev.updateStateOnServer('deviceIsOnline', value=True, uiValue="Online")
            dev.setErrorStateOnServer(None)
            self.WaitInterval = 0

            return result

        except Exception as error:

            indigo.server.log(u"Error connecting to Device:" + str(dev.name) +"Error is:"+str(error))
            self.WaitInterval = 60
            if self.debugLevel >= 2:
                self.debugLog(u"Device is offline. No data to return. ")
            dev.updateStateOnServer('deviceIsOnline', value=False, uiValue="Offline")
            dev.updateStateOnServer('powerStatus', value='offline', uiValue='Offline')
            #dev.updateStateOnServer('powerStatus', value = 'offline')
            dev.setErrorStateOnServer(u'Offline')
            result = None
            return result

    def getAPIDataConsumption(self, dev):
        """
        The getTheData() method is used to retrieve  API Client Data
        """
        if self.debugLevel >= 2:
            self.debugLog(u"getAPIDataConsumption METHOD method called.")

        try:
            url = f"http{self.https_flag}://{dev.pluginProps['sourceXML']}/api/v1/consumption"
            headers = self.create_headers( dev)
            url = f"http{self.https_flag}://{dev.pluginProps['sourceXML']}/api/v1/consumption"
            r = requests.get(url,timeout=15,  headers=headers, allow_redirects=False)
            result = r.json()
            if self.debugLevel >= 2:
                self.debugLog(u"Result:" + str(result))
            self.WaitInterval = 0
            return result

        except Exception as error:
            self.logger.debug("Exception in LegacyConsumption Data. Perhaps doesn't exist.")
            result = None
            return result

    def checkThePanels_New(self,dev):
        if self.debugLevel >= 2:
            self.debugLog(u'check thepanels called')
        if dev.pluginProps['activatePanels']:
            self.thePanels = self.getthePanels(dev)
            try:
                if self.thePanels is not None:
                    x = 1
                    update_time = t.strftime("%m/%d/%Y at %H:%M")
                    dev.updateStateOnServer('panelLastUpdated', value=update_time  )
                    dev.updateStateOnServer('panelLastUpdatedUTC', value=float(t.time())  )                  
                    for dev in indigo.devices.iter('self.EnphasePanelDevice'):
                        for panel in self.thePanels:
                            if float(dev.states['serialNo']) == float(panel['serialNumber']):
                                #self.logger.error(u'Matched Panel Found:'+str(panel['serialNumber']))
                                #deviceName = 'Enphase SolarPanel ' + str(x)
                                #self.logger.error(u"Enphase Panel SN:"+str(str(panel['serialNumber'])))
                                if dev.states['producing']:
                                    dev.updateStateOnServer('watts',value=int(panel['lastReportWatts']),uiValue=str(panel['lastReportWatts']))
                                dev.updateStateOnServer('lastCommunication', value=str(datetime.datetime.fromtimestamp( int(panel['lastReportDate'])).strftime('%c')))
                                #dev.updateStateOnServer('serialNo', value=float(panel['serialNumber']))
                                dev.updateStateOnServer('maxWatts', value=int(panel['maxReportWatts']))
                                dev.updateStateOnServer('deviceLastUpdated', value=update_time)
                                dev.updateStateOnServer('deviceIsOnline', value=True, uiValue="Online")
                                dev.setErrorStateOnServer(None)

            except Exception as error:
                self.errorLog('error within checkthePanels:'+str(error))
                if self.debugLevel >= 2:
                    self.logger.debug(u"Device is offline. No data to return. ", exc_info=True)
                dev.updateStateOnServer('deviceIsOnline', value=False, uiValue="Offline")
                dev.setErrorStateOnServer(u'Offline')
                result = None

                return result
        return


    def checkPanelInventory(self,dev):
        if self.debugLevel >= 2:
            self.debugLog(u"checkPanelInventory Enphase Panels method called.")

        if dev.pluginProps['activatePanels'] and dev.states['deviceIsOnline']:
            self.inventoryDict = self.getInventoryData(dev)
            try:
                if self.inventoryDict is not None:
                    for dev in indigo.devices.iter('self.EnphasePanelDevice'):
                        for devices in self.inventoryDict[0]['devices']:
                            #if self.debugLevel >=2:
                               # self.debugLog(u'checking serial numbers')
                               # self.errorLog(u'device serial:'+str(int(dev.states['serialNo'])))
                               # self.errorLog(u'panel serial no:'+str(devices['serial_num']))
                            #self.errorLog(u'Dev.states Producing type is' + str(type(dev.states['producing'])))
                            #self.errorLog(u'Devices Producing type is' + str(type(devices['producing'])))
                            if float(dev.states['serialNo']) == float(devices['serial_num']):
                                if dev.states['producing']==True and devices['producing']==False:
                                    if self.debugLevel >= 1:
                                        self.debugLog(u'Producing: States true, devices(producing) False: devices[producing] equals:'+str(devices['producing']))
                                    #  change only once
                                    dev.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)
                                    dev.updateStateOnServer('watts', value=0, uiValue='--')
                                if dev.states['producing'] == False and devices['producing'] == True:
                                    if self.debugLevel >= 1:
                                        self.debugLog(u'States Producing False, and devices now shows True: device(producing):' + str(devices['producing']))
                                    dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)
                                    dev.updateStateOnServer('watts', value=dev.states['watts'], uiValue=str(dev.states['watts']))

                                dev.updateStateOnServer('status',   value=str(devices['device_status']))
                                dev.updateStateOnServer('modelNo', value=str(devices['part_num']))
                                dev.updateStateOnServer('producing',   value=devices['producing'])
                                dev.updateStateOnServer('communicating', value=devices['communicating'])
                    return

            except Exception as error:
                self.errorLog('error within checkPanelInventory:'+str(error))
                if self.debugLevel >= 2:
                    self.debugLog(u"Device is offline. No data to return. ")
                dev.updateStateOnServer('deviceIsOnline', value=False, uiValue="Offline")
                dev.setErrorStateOnServer(u'Offline')
                result = None
                return result

        return


    def getInventoryData(self, dev):

        if self.debugLevel >= 2:
            self.debugLog(u"getInventoryData Enphase Panels method called.")
        try:
            url = f"http://{dev.pluginProps['sourceXML']}/inventory.json"
            headers = self.create_headers(dev)
            url = f"http://{dev.pluginProps['sourceXML']}/inventory.json"
            r = requests.get(url, timeout =15, headers=headers,allow_redirects=False)
            result = r.json()
            if self.debugLevel >= 2:
                self.debugLog(u"Inventory Result:" + str(result))
            return result

        except Exception as error:

            indigo.server.log(u"Error connecting to Device:" + dev.name)
            if self.debugLevel >= 2:
                self.debugLog(u"Device is offline. No data to return. ")
            # dev.updateStateOnServer('deviceTimestamp', value=t.time())
            result = None
            self.WaitInterval = 60
            return result


    def getthePanels(self, dev):
        if self.debugLevel >= 2:
            self.debugLog(u"getthePanels Enphase Envoy method called.")

        if self.serial_number_last_six =="":
            if self.get_serial_number(dev):
                self.logger.debug("Found the correct Serial Number.  Continuing.")
            else:
                self.logger.debug("Error getting Serial Number.  Cannot update panels unfortunately")
                return

        if dev.states['deviceIsOnline']:
            try:
                headers = self.create_headers( dev)
                url = f"http{self.https_flag}://{dev.pluginProps['sourceXML']}api/v1/production/inverters"
                if self.debugLevel >=2:
                    self.debugLog(u"getthePanels: Password:"+str(self.serial_number_last_six))
                if len(headers) >0:  # Using token
                    r = requests.get(url,headers=headers, timeout=30, allow_redirects=False)
                else:
                    r = requests.get(url, auth=HTTPDigestAuth('envoy',self.serial_number_last_six), timeout=30, allow_redirects=False)
                result = r.json()
                if self.debugLevel >= 2:
                    self.debugLog(f"Inverter Result:{result}")
                if "status" in result:
                    if result["status"] ==  401:
                        self.logger.info(f"Error getting Panel Data: Error : {result}")
                        return None
                return result

            except requests.exceptions.ReadTimeout as e:
                self.logger.debug("ReadTimeout with get Panel Devices:" + str(e))
                return None
            except requests.exceptions.Timeout as e:
                self.logger.debug("ReadTimeout with get Panel Devices:" + str(e))
                return None
            except requests.exceptions.ConnectionError as e:
                self.logger.debug("ReadTimeout with get Panel Devices:" + str(e))
                return None
            except requests.exceptions.ConnectTimeout as e:
                self.logger.debug("ReadTimeout with get Panel Devices:" + str(e))
                result = None
                return result

            except Exception as error:

                indigo.server.log(u"Error connecting to Device:" + dev.name)
                if self.debugLevel >= 2:
                    self.logger.debug(u"Device is offline. No data to return. ", exc_info=True)
                # dev.updateStateOnServer('deviceTimestamp', value=t.time())
                dev.updateStateOnServer('deviceIsOnline', value=False, uiValue="Offline")
                for paneldevice in indigo.devices.iter('self.EnphasePanelDevice'):
                    paneldevice.updateStateOnServer('deviceIsOnline', value=False, uiValue="Offline")
                    paneldevice.updateStateOnServer('watts', value=0)
                    paneldevice.setErrorStateOnServer(u'Offline')
                self.WaitInterval = 60
                result = None
                return result

    def legacyParseStateValues(self, dev, results):
        """
        The parseStateValues() method walks through the dict and assigns the
        corresponding value to each device state.
        """
        if self.debugLevel >= 2:
            self.debugLog(u"Saving Values method called.")

        try:
            dev.updateStateOnServer('wattHoursLifetime', value=int(results['wattHoursLifetime']))
            dev.updateStateOnServer('wattHoursSevenDays', value=int(results['wattHoursSevenDays']))
            dev.updateStateOnServer('wattHoursToday', value=int(results['wattHoursToday']))
            dev.updateStateOnServer('wattsNow', value=int(results['wattsNow']))
            update_time = t.strftime("%m/%d/%Y at %H:%M")
            dev.updateStateOnServer('deviceLastUpdated', value=update_time)

            if int(results['wattsNow'])>0:
                dev.updateStateOnServer('powerStatus', value="producing", uiValue="Producing Energy")
                dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)
            elif int(results['wattsNow'])<=0:
                dev.updateStateOnServer('powerStatus', value="idle", uiValue="Not Producing Energy")
                dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)

            if self.debugLevel >= 1:
                self.debugLog("State Image Selector:"+str(dev.displayStateImageSel))

        except Exception as error:
             if self.debugLevel >= 2:
                 self.errorLog(u"Saving Values errors:"+str(error))

    def setproductionMax(self, device, currentproduction):
        try:
            maxwattsinDeviceToday = int(device.states['productionWattsMaxToday'])
            maxwattsinDeviceWeek = int(device.states['productionWattsMaxWeek'])
            maxwattsinDeviceEver = int(device.states['productionWattsMaxEver'])

            if currentproduction >= maxwattsinDeviceToday:
                ## Max has been reached currently
                device.updateStateOnServer('productionWattsMaxToday', value=int(currentproduction))
            if currentproduction >= maxwattsinDeviceWeek:
                ## Max has been reached currently
                device.updateStateOnServer('productionWattsMaxWeek', value=int(currentproduction))
            if currentproduction >= maxwattsinDeviceEver:
                ## Max has been reached currently
                device.updateStateOnServer('productionWattsMaxEver', value=int(currentproduction))


        except Exception as error:
            if self.debugLevel >=2:
                self.logger.exception("Caught Exception")


    def parseStateValues(self, dev,data):
        """
        The parseStateValues() method walks through the dict and assigns the
        corresponding value to each device state.
        """

        #testdata2 = {u'production': [{u'activeCount': 43, u'wNow': 1912, u'readingTime': 1493848912, u'type': u'inverters',u'whLifetime': 9422470.6777777784},
        #                 {u'whToday': 51894.915000000001, u'pwrFactor': 0.93000000000000005, u'readingTime': 1493848913,u'activeCount': 1, u'rmsVoltage': 250.69399999999999, u'reactPwr': 541.96500000000003,
        #                  u'whLifetime': 9352075.9149999991, u'apprntPwr': 1916.5229999999999,u'wNow': 1778.6320000000001, u'type': u'eim', u'whLastSevenDays': 326631.91499999998,
         #                 u'rmsCurrent': 15.289999999999999}], u'consumption': [{u'varhLagLifetime': 0, u'rmsVoltage': 0, u'pwrFactor': 0, u'whToday': 0, u'vahToday': 0,
        #     u'varhLeadLifetime': 0, u'varhLeadToday': 0, u'activeCount': 0, u'varhLagToday': 0, u'vahLifetime': 0,u'reactPwr': 0, u'whLifetime': 0, u'apprntPwr': 0, u'wNow': 0, u'type': u'eim', u'whLastSevenDays': 0,
        #     u'rmsCurrent': 0}]}

        #self.finalDict = testdata2
        #testdata = {u'production': [{u'activeCount': 32, u'wNow': 303, u'readingTime': 1484494980, u'type': u'inverters', u'whLifetime': 1799748.9794444444}, {u'whToday': 137.262, u'pwrFactor': 0.53, u'readingTime': 1484494980, u'activeCount': 1, u'rmsVoltage': 248.215, u'reactPwr': 490.766, u'whLifetime': 1321326.262, u'apprntPwr': 596.966, u'wNow': 316.044, u'type': u'eim', u'whLastSevenDays': 116064.262, u'rmsCurrent': 4.81}], u'consumption': [{u'varhLagLifetime': 913691.045, u'rmsVoltage': 248.132, u'pwrFactor': 0.35, u'whToday': 6075.567, u'vahToday': 8331.054, u'varhLeadLifetime': 912659.572, u'varhLeadToday': 4580.572, u'readingTime': 1484494980, u'activeCount': 1, u'varhLagToday': 4093.045, u'vahLifetime': 2530344.054, u'reactPwr': 402.82, u'whLifetime': 1756854.567, u'apprntPwr': 3780.981, u'wNow': 1337.481, u'type': u'eim', u'whLastSevenDays': 161357.567, u'rmsCurrent': 15.238}]}
        #self.finalDict = testdata
        #data = {u'production': [{u'activeCount': 32, u'readingTime': 1592320372, u'type': u'inverters', u'whLifetime': 30205473, u'wNow': 6332}, {u'varhLagLifetime': 0.0, u'whToday': 0.0, u'vahToday': 0.0, u'varhLeadLifetime': 0.0, u'pwrFactor': 0.99, u'readingTime': 1592320555, u'whLastSevenDays': 0.0, u'varhLeadToday': 0.0, u'activeCount': 0, u'varhLagToday': 0.0, u'vahLifetime': 0.0, u'reactPwr': 668.095, u'rmsVoltage': 241.442, u'apprntPwr': 6923.603, u'wNow': 6829.524, u'measurementType': u'production', u'type': u'eim', u'whLifetime': 0.0, u'rmsCurrent': 57.352}], u'storage': [{u'readingTime': 0, u'whNow': 0, u'activeCount': 0, u'state': u'idle', u'wNow': 0, u'type': u'acb'}], u'consumption': [{u'varhLagLifetime': 0.0, u'whToday': 0.0, u'vahToday': 0.0, u'varhLeadLifetime': 0.0, u'pwrFactor': 0.49, u'readingTime': 1592320555, u'whLastSevenDays': 0.0, u'varhLeadToday': 0.0, u'activeCount': 0, u'varhLagToday': 0.0, u'vahLifetime': 0.0, u'reactPwr': -668.095, u'rmsVoltage': 241.537, u'apprntPwr': 13915.818, u'wNow': 6829.524, u'measurementType': u'total-consumption', u'type': u'eim', u'whLifetime': 0.0, u'rmsCurrent': 57.614}, {u'varhLagLifetime': 0.0, u'whToday': 0, u'vahToday': 0, u'varhLeadLifetime': 0.0, u'pwrFactor': 0.0, u'readingTime': 1592320555, u'whLastSevenDays': 0, u'varhLeadToday': 0, u'activeCount': 0, u'varhLagToday': 0, u'vahLifetime': 0.0, u'reactPwr': 0.0, u'rmsVoltage': 241.632, u'apprntPwr': 31.635, u'wNow': 0.0, u'measurementType': u'net-consumption', u'type': u'eim', u'whLifetime': 0.0, u'rmsCurrent': 0.262}]}
        #roque data
        #data = {u'production': [{u'activeCount': 32, u'readingTime': 1628529482, u'type': u'inverters', u'whLifetime': 46071778, u'wNow': 3945}, {u'varhLagLifetime': 0.0, u'whToday': 0.0, u'vahToday': 0.0, u'varhLeadLifetime': 0.0, u'pwrFactor': 0.97, u'readingTime': 1628529514, u'whLastSevenDays': 0.0, u'varhLeadToday': 0.0, u'activeCount': 0, u'varhLagToday': 0.0, u'vahLifetime': 0.0, u'reactPwr': 639.174, u'rmsVoltage': 241.337, u'apprntPwr': 3642.217, u'wNow': 3538.273, u'measurementType': u'production', u'type': u'eim', u'whLifetime': 0.0, u'rmsCurrent': 30.183}], u'storage': [{u'readingTime': 0, u'whNow': 0, u'activeCount': 0, u'state': u'idle', u'wNow': 0, u'type': u'acb'}], u'consumption': [{u'varhLagLifetime': 0.0, u'whToday': 0.0, u'vahToday': 0.0, u'varhLeadLifetime': 0.0, u'pwrFactor': 0.48, u'readingTime': 1628529514, u'whLastSevenDays': 0.0, u'varhLeadToday': 0.0, u'activeCount': 0, u'varhLagToday': 0.0, u'vahLifetime': 0.0, u'reactPwr': -639.174, u'rmsVoltage': 241.376, u'apprntPwr': 7348.878, u'wNow': 3538.273, u'measurementType': u'total-consumption', u'type': u'eim', u'whLifetime': 0.0, u'rmsCurrent': 30.446}, {u'varhLagLifetime': 0.0, u'whToday': 0, u'vahToday': 0, u'varhLeadLifetime': 0.0, u'pwrFactor': 0.0, u'readingTime': 1628529514, u'whLastSevenDays': 0, u'varhLeadToday': 0, u'activeCount': 0, u'varhLagToday': 0, u'vahLifetime': 0.0, u'reactPwr': -0.0, u'rmsVoltage': 241.415, u'apprntPwr': 31.626, u'wNow': 0.0, u'measurementType': u'net-consumption', u'type': u'eim', u'whLifetime': 0.0, u'rmsCurrent': 0.263}]}

        #unmetered
        #data = {u'production': [{u'activeCount': 32, u'readingTime': 1628431003, u'type': u'inverters', u'whLifetime': 46011634, u'wNow': 4706}, {u'varhLagLifetime': 0.0, u'whToday': 0.0, u'vahToday': 0.0, u'varhLeadLifetime': 0.0, u'pwrFactor': 0.98, u'readingTime': 1628431183, u'whLastSevenDays': 0.0, u'varhLeadToday': 0.0, u'activeCount': 0, u'varhLagToday': 0.0, u'vahLifetime': 0.0, u'reactPwr': 662.891, u'rmsVoltage': 244.078, u'apprntPwr': 4348.023, u'wNow': 4257.374, u'measurementType': u'production', u'type': u'eim', u'whLifetime': 0.0, u'rmsCurrent': 35.615}], u'storage': [{u'readingTime': 0, u'whNow': 0, u'activeCount': 0, u'state': u'idle', u'wNow': 0, u'type': u'acb'}], u'consumption': [{u'varhLagLifetime': 0.0, u'whToday': 0.0, u'vahToday': 0.0, u'varhLeadLifetime': 0.0, u'pwrFactor': 0.49, u'readingTime': 1628431183, u'whLastSevenDays': 0.0, u'varhLeadToday': 0.0, u'activeCount': 0, u'varhLagToday': 0.0, u'vahLifetime': 0.0, u'reactPwr': -662.891, u'rmsVoltage': 244.026, u'apprntPwr': 8754.438, u'wNow': 4257.374, u'measurementType': u'total-consumption', u'type': u'eim', u'whLifetime': 0.0, u'rmsCurrent': 35.875}, {u'varhLagLifetime': 0.0, u'whToday': 0, u'vahToday': 0, u'varhLeadLifetime': 0.0, u'pwrFactor': 0.0, u'readingTime': 1628431183, u'whLastSevenDays': 0, u'varhLeadToday': 0, u'activeCount': 0, u'varhLagToday': 0, u'vahLifetime': 0.0, u'reactPwr': 0.0, u'rmsVoltage': 243.974, u'apprntPwr': 31.778, u'wNow': 0.0, u'measurementType': u'net-consumption', u'type': u'eim', u'whLifetime': 0.0, u'rmsCurrent': 0.26}]}      #testdata4 = {"production":[{"type":"inverters","activeCount":26,"readingTime":1583573417,"wNow":1735,"whLifetime":26678},{"type":"eim","activeCount":0,"measurementType":"production","readingTime":1583573476,"wNow":-2.835,"whLifetime":0.0,"varhLeadLifetime":0.0,"varhLagLifetime":0.0,"vahLifetime":0.0,"rmsCurrent":0.362,"rmsVoltage":717.437,"reactPwr":0.829,"apprntPwr":86.904,"pwrFactor":-0.06,"whToday":0.0,"whLastSevenDays":0.0,"vahToday":0.0,"varhLeadToday":0.0,"varhLagToday":0.0}],"consumption":[{"type":"eim","activeCount":0,"measurementType":"total-consumption","readingTime":1583573476,"wNow":-1.149,"whLifetime":0.0,"varhLeadLifetime":0.0,"varhLagLifetime":0.0,"vahLifetime":0.0,"rmsCurrent":0.825,"rmsVoltage":717.603,"reactPwr":-1.6,"apprntPwr":592.15,"pwrFactor":-0.0,"whToday":0.0,"whLastSevenDays":0.0,"vahToday":0.0,"varhLeadToday":0.0,"varhLagToday":0.0},{"type":"eim","activeCount":0,"measurementType":"net-consumption","readingTime":1583573476,"wNow":1.686,"whLifetime":0.0,"varhLeadLifetime":0.0,"varhLagLifetime":0.0,"vahLifetime":0.0,"rmsCurrent":0.463,"rmsVoltage":717.769,"reactPwr":-0.771,"apprntPwr":110.751,"pwrFactor":0.05,"whToday":0,"whLastSevenDays":0,"vahToday":0,"varhLeadToday":0,"varhLagToday":0}],"storage":[{"type":"acb","activeCount":0,"readingTime":0,"wNow":0,"whNow":0,"state":"idle"}]}
        #JohnMcEvoy
        #data =  {u'wattHoursLifetime': 46011634, u'wattHoursToday': 3876, u'wattsNow': 4707, u'wattHoursSevenDays': 294504}

        #self.finalDict = testdata4

        if self.debugLevel >= 2:
            self.debugLog(u"Saving Values method called.")
            #self.debugLog(str(self.finalDict))

        try:
            envoyType = dev.states['typeEnvoy']
            consumptionWatts =0
            productionWatts =0
            # Check that finalDict contains a production list

            if data is None:
                if self.debugLevel >= 2:
                    self.debugLog(u"no data found.")
                return

            if "production" in data:
                dev.updateStateOnServer('numberInverters', value=int(data['production'][0]['activeCount']))
            else:
                if self.debugLevel >= 2:
                    self.debugLog(u"no Production result found.")
                dev.updateStateOnServer('numberInverters', value=0)

            if envoyType == "Metered":
                if len(data['production']) > 1:
                    dev.updateStateOnServer('productionWattsNow', value=int(data['production'][1]['wNow']))
                    productionWatts = int(data['production'][1]['wNow'])

                    dev.updateStateOnServer('production7days', value=int(data['production'][1]['whLastSevenDays']))
                    dev.updateStateOnServer('productionWattsToday', value=int(data['production'][1]['whToday']))
                    dev.updateStateOnServer('productionwhLifetime', value=int(data['production'][1]['whLifetime']))
                else:
                    if self.debugLevel >= 2:
                        self.debugLog(u"no Production 2 result found.")
                    dev.updateStateOnServer('productionWattsNow', value=0)
                    dev.updateStateOnServer('production7days',value=0)
                    dev.updateStateOnServer('productionWattsToday',value=0)

            elif envoyType == "Unmetered":
                if "wattsNow" in data:
                    dev.updateStateOnServer('productionWattsNow', value=int(data['wattsNow']))
                    productionWatts = int(data['wattsNow'])
                    if data is not None:
                        if 'wattHoursSevenDays' in data:
                            dev.updateStateOnServer('production7days', value=int(data['wattHoursSevenDays']))
                        if 'wattHoursToday' in data:
                            dev.updateStateOnServer('productionWattsToday', value=int(data['wattHoursToday']))
                        if 'wattHoursLifetime' in data:
                            dev.updateStateOnServer('productionwhLifetime', value=int(data['wattHoursLifetime']))

            if envoyType == "Metered":
                if "consumption" in data:
                    dev.updateStateOnServer('consumptionWattsNow', value=int(data['consumption'][0]['wNow']))
                    consumptionWatts = int(data['consumption'][0]['wNow'])
                    dev.updateStateOnServer('consumption7days', value=int(data['consumption'][0]['whLastSevenDays']))
                    dev.updateStateOnServer('consumptionwhLifetime',  value=int(data['consumption'][0]['whLifetime']))
                    dev.updateStateOnServer('consumptionWattsToday', value=int(data['consumption'][0]['whToday']))
                    if len(data['consumption'])>1:
                        dev.updateStateOnServer('netConsumptionWattsNow', value=int(data['consumption'][1]['wNow']))
                        dev.updateStateOnServer('netconsumptionwhLifetime',value=int(data['consumption'][1]['whLifetime']))
                    else:
                        if self.debugLevel >=2:
                            self.debugLog(u'No netConsumption being reporting.....Calculating....')
                        # Calculate?
                        #
                        netConsumption = int(consumptionWatts) - int(productionWatts)
                        dev.updateStateOnServer('netConsumptionWattsNow', value=int(netConsumption))
            elif envoyType == "Unmetered":
                    # does seem reported, use the api/consumption endpoint which may or may not exisit on U versions
                    # not consumption data appears possible
                    dev.updateStateOnServer('consumptionWattsNow',value=0,uiValue="Not Reported")
                    dev.updateStateOnServer('consumption7days', value=int(0),uiValue="Not Reported")
                    dev.updateStateOnServer('consumptionWattsToday', value=int(0),uiValue="Not Reported")
                    dev.updateStateOnServer('consumptionwhLifetime', value=int(0),uiValue="Not Reported")
                    dev.updateStateOnServer('netConsumptionWattsNow', value=int(0),uiValue="Not Reported")

                    # if consumptionData is not None:
                    #     if 'wattsNow' in consumptionData:
                    #         consumptionWatts = int(consumptionData['wattsNow'])
                    #         dev.updateStateOnServer('consumptionWattsNow', consumptionWatts)
                    # #dev.updateStateOnServer('consumptionWattsNow', value=int(self.finalDict['consumption'][0]['wNow']))
                    # #consumptionWatts = int(self.finalDict['consumption'][0]['wNow'])  ## total consumption
                    #     if 'wattHoursSevenDays' in consumptionData:
                    #         dev.updateStateOnServer('consumption7days', value=int(consumptionData['wattHoursSevenDays']))
                    #     if 'wattHoursToday' in consumptionData:
                    #         dev.updateStateOnServer('consumptionWattsToday', value=int(consumptionData['wattHoursToday']))
                    #     if 'wattHoursLifetime' in consumptionData:
                    #         dev.updateStateOnServer('consumptionwhLifetime', value=int(consumptionData['wattHoursLifetime']))
                    # else:
                    #     self.logger.debug(str("API Consumption returned nothing."))
                    # if self.debugLevel >= 2:
                    #     self.debugLog(u'No netConsumption being reporting.....Calculating....')
                    # # Calculate?
                    # #
                    # netConsumption = int(consumptionWatts) - int(productionWatts)
                    # dev.updateStateOnServer('netConsumptionWattsNow', value=int(netConsumption))

            else:
                if self.debugLevel >= 2:
                    self.debugLog(u"no Consumption result found.")

            if envoyType == "Metered":
                if "storage" in data:
                    dev.updateStateOnServer('storageActiveCount', value=int(data['storage'][0]['activeCount']))
                    dev.updateStateOnServer('storageWattsNow', value=int(data['storage'][0]['wNow']))
                    dev.updateStateOnServer('storageState', value=data['storage'][0]['state'])
                    #dev.updateStateOnServer('storagePercentFull', value=int(self.finalDict['storage'][0]['percentFull']))
            else:
                if self.debugLevel >= 2:
                    self.debugLog(u"no Storage result found.")
                dev.updateStateOnServer('storageState', value='No Data')

            update_time = t.strftime("%m/%d/%Y at %H:%M")
            dev.updateStateOnServer('deviceLastUpdated', value=update_time)
            if envoyType == "Metered":
                reading_time = datetime.datetime.fromtimestamp(data['production'][1]['readingTime'])
            #format_reading_time = t.strftime()
                dev.updateStateOnServer('readingTime', value=str(reading_time))
                timeDifference = int(t.time() - t.mktime(reading_time.timetuple()))
                dev.updateStateOnServer('secsSinceReading', value=timeDifference)
            if self.debugLevel >= 2:
                self.debugLog(u"State Image Selector:"+str(dev.displayStateImageSel))

            ##
            self.setproductionMax(dev, productionWatts)


            if envoyType == "Metered":

                if productionWatts >= consumptionWatts and (dev.states['powerStatus']=='importing' or dev.states['powerStatus']=='offline'):
                    #Generating more Power - and a change
                    # If Generating Power - but device believes importing - recent change unpdate to refleect
                    if self.debugLevel >= 2:
                        self.debugLog(u'**CHANGED**: Exporting Power')

                    dev.updateStateOnServer('powerStatus', value = 'exporting', uiValue='Exporting Power')
                    dev.updateStateOnServer('generatingPower', value=True)
                    dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)
                    if self.debugLevel >= 2:
                        self.debugLog("State Image Selector:" + str(dev.displayStateImageSel))

                if productionWatts < consumptionWatts and (dev.states['powerStatus'] == 'exporting' or dev.states['powerStatus']=='offline'):
                    #Must be opposite or and again a change only
                    if self.debugLevel >= 2:
                        self.debugLog(u'**CHANGED**: Importing power')
                    dev.updateStateOnServer('powerStatus', value='importing', uiValue='Importing Power')
                    dev.updateStateOnServer('generatingPower', value=False)
                    dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)
                    if self.debugLevel >= 2:
                        self.debugLog(u"State Image Selector:" + str(dev.displayStateImageSel))
            elif envoyType == "Unmetered":
            # does seem reported, use the api/consumption endpoint which may or may not exisit on U versions
            # not consumption data appears possible
                self.logger.debug("Envoy Unmetered equivalent used for Status:")
                self.logger.debug("Producing Watts:" + str(productionWatts))
                if productionWatts > 0:
                    ## change meaning of generatingPower here for unmetered to any power, not just net power
                    dev.updateStateOnServer('generatingPower', value=True, uiValue="Producing Power")
                    dev.updateStateOnServer('powerStatus', value="producing", uiValue="Producing Energy")
                    dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)
                    if self.debugLevel >= 2:
                        self.debugLog("State Image Selector:" + str(dev.displayStateImageSel))
                elif productionWatts <= 0:
                    dev.updateStateOnServer('generatingPower', value=False, uiValue="No Power Production")
                    dev.updateStateOnServer('powerStatus', value="idle", uiValue="Not Producing Energy")
                    dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)

            for costdev in indigo.devices.iter('self.EnphaseEnvoyCostDevice'):
                if self.debugLevel >2:
                    self.debugLog(u'Updating Cost Device')
                self.updateCostDevice(dev, costdev)

        except Exception as error:
             if self.debugLevel >= 2:
                 self.errorLog(u"Saving Values errors:"+str(error) + str(error) )
                 self.logger.exception("Saving Values Exception")

    def updateCostDevice(self, dev, costdev):
        if self.debugLevel>=2:
            self.debugLog(u'updateCostDevice Run')
        # get current Tarrif
        try:
            tariffkwhconsumption = float(costdev.pluginProps['envoyTariffkWhConsumption'])
            tariffkwhproduction = float(costdev.pluginProps['envoyTariffkWhProduction'])
        except Exception as error:
            if self.debugLevel>=2:
                self.debugLog(u'error with Tarriff kwh,please update device settings. Defaulting to $1.0/kwh:' + str(error)   )
            tariffkwhproduction = 1.0
            tariffkwhconsumption = 1.0

        try:
            productionkwhToday = float(dev.states['productionWattsToday']/1000 )
            productionTarrifToday = float(productionkwhToday * tariffkwhproduction)
            costdev.updateStateOnServer('productionTarrifToday', value='${:,.2f}'.format(productionTarrifToday))
            costdev.updateStateOnServer('productionkWToday',value=float(dev.states['productionWattsToday'])/1000)

            consumptionkwhToday = float(dev.states['consumptionWattsToday']/1000 )
            consumptionTarrifToday = float(consumptionkwhToday * tariffkwhconsumption)
            costdev.updateStateOnServer('consumptionTarrifToday', value='${:,.2f}'.format(consumptionTarrifToday))
            costdev.updateStateOnServer('consumptionkWToday', value=float(dev.states['consumptionWattsToday'])/1000)

            productionkwh7days = float(dev.states['production7days']/1000 )
            productionTarrif7days = float(productionkwh7days * tariffkwhproduction)
            costdev.updateStateOnServer('productionTarrif7days', value='${:,.2f}'.format(productionTarrif7days))
            costdev.updateStateOnServer('productionkW7days', value=float(dev.states['production7days'])/1000)

            consumptionkwh7days = float(dev.states['consumption7days']/1000 )
            consumptionTarrif7days = float(consumptionkwh7days * tariffkwhconsumption)
            costdev.updateStateOnServer('consumptionTarrif7days', value='${:,.2f}'.format(consumptionTarrif7days))
            costdev.updateStateOnServer('consumptionkW7days', value=float(dev.states['consumption7days']/1000))

            productionkwhLifetime = float(dev.states['productionwhLifetime']/1000 )
            productionTarrifLifetime = float(productionkwhLifetime * tariffkwhproduction)
            costdev.updateStateOnServer('productionTarrifLifetime', value='${:,.2f}'.format(productionTarrifLifetime))
            costdev.updateStateOnServer('productionkwhLifetime',value=float(productionkwhLifetime))

            consumptionkwhLifetime = float(dev.states['consumptionwhLifetime']/1000 )
            consumptionTarrifLifetime = float(consumptionkwhLifetime * tariffkwhconsumption)
            costdev.updateStateOnServer('consumptionTarrifLifetime', value='${:,.2f}'.format(consumptionTarrifLifetime))
            costdev.updateStateOnServer('consumptionkwhLifetime', value=float(consumptionkwhLifetime))

            netconsumptionkwhLifetime = float(dev.states['netconsumptionwhLifetime'] / 1000)
            netconsumptionTarrifLifetime = float(netconsumptionkwhLifetime * tariffkwhconsumption)
            costdev.updateStateOnServer('netconsumptionTarrifLifetime', value='${:,.2f}'.format(netconsumptionTarrifLifetime))
            costdev.updateStateOnServer('netconsumptionkwhLifetime', value=float(netconsumptionkwhLifetime))

            # change to cost.
            netTarrif7days = float (productionTarrif7days - consumptionTarrif7days)
            netTarrifToday = float (productionTarrifToday - consumptionTarrifToday)
            netkw7Days = float(productionkwh7days - consumptionkwh7days)
            netkwToday = float(productionkwhToday-consumptionkwhToday)

            costdev.updateStateOnServer('netkWToday', value=netkwToday)
            costdev.updateStateOnServer('netkW7days', value=netkw7Days)

            costdev.updateStateOnServer('netTarrifToday',  value='${:,.2f}'.format(netTarrifToday ))
            costdev.updateStateOnServer('netTarrif7days', value='${:,.2f}'.format(netTarrif7days ))

            update_time = t.strftime("%m/%d/%Y at %H:%M")
            costdev.updateStateOnServer('deviceLastUpdated', value=update_time)
            return

        except Exception as error:
            self.logger.exception(u'Exception within Cost Device Calculation:'+str(error))
            return





    def setStatestonil(self, dev):
        if self.debugLevel >= 2:
            self.debugLog(u'setStates to nil run')

    def generatePanelDevices(self, valuesDict, typeId, devId):
        if self.debugLevel >= 2:
            self.debugLog(u'generate Panels run')
        try:
            #delete all panel devices first up
            dev = indigo.devices[devId]
            if self.debugLevel>=2:
                self.debugLog(u'Folder ID'+str(dev.folderId))
            self.thePanels = self.getthePanels(dev)

            if self.thePanels is not None:
                x = 1
                for array in self.thePanels:
                    noDevice = True
                    for paneldevice in indigo.devices.iter('self.EnphasePanelDevice'):
                       # self.logger.debug(str(paneldevice.states['serialNo'])+"& array:"+  str(array['serialNumber']))
                        if float(paneldevice.states['serialNo']) == float(array['serialNumber']):  # check all exisiting devices for serialNo - if doesnt create
                            self.logger.debug(u'Matching Serial Number found. Device being skipped.')
                            noDevice=False

                    #self.logger.error("Serial Number:"+str(serialNumber))
                    deviceName = "Enphase Panel "+ str(x)
                    if noDevice:
                        serialNumber = float(array['serialNumber'])
                        update_time = t.strftime("%m/%d/%Y at %H:%M")
                        #self.logger.error(u'SerialNumber:'+str(array['serialNumber']))
                        stateList = [
                            {'key': 'serialNo', 'value': float(array['serialNumber'])},
                            {'key': 'watts', 'value': int(array['lastReportWatts']) },
                            {'key': 'lastCommunication', 'value': str(datetime.datetime.fromtimestamp(int(array['lastReportDate'])).strftime('%c'))},
                            {'key': 'maxWatts', 'value': 0},
                            {'key': 'deviceLastUpdated', 'value': update_time },
                            {'key': 'deviceIsOnline', 'value': True},
                            {'key': 'status', 'value': 'starting communication'},
                            {'key': 'modelNo', 'value': 'unknown'},
                            {'key': 'producing', 'value': False},
                            {'key': 'communicating', 'value': False}
                        ]
                        device = indigo.device.create(
                            address=str(serialNumber),
                            deviceTypeId='EnphasePanelDevice',
                            name=self.getUniqueDeviceName(deviceName),
                            protocol=indigo.kProtocol.Plugin,
                            folder=dev.folderId)

                        self.logger.info(str('Panel Device Created:'+str(self.getUniqueDeviceName(deviceName))))
                        device.updateStatesOnServer(stateList)
                        self.sleep(0.1)

                    x=x+1
            #now fill with data
            self.sleep(2)
            self.checkThePanels_New(dev)


        except Exception as error:
            self.logger.exception("Exception within Generate Panels")
            self.errorLog(u'error within generate panels'+str(error))

    ########################################
    def getUniqueDeviceName(self, seedName):
        seedName = seedName.strip()
        if (seedName not in indigo.devices):
            return seedName
        else:
            counter = 1
            candidate = seedName + " " + str(counter)
            while candidate in indigo.devices:
                counter = counter + 1
                candidate = seedName + " " + str(counter)
            return candidate

    ########################################

    def deletePanelDevices(self, valuesDict, typeId, devId):
        if self.debugLevel >= 2:
            self.debugLog(u'Delete Panels run')

        try:
            # delete all panel devices first up
            for dev in indigo.devices.iter('self.EnphasePanelDevice'):
                indigo.device.delete(dev.id)
                if self.debugLevel > 2:
                    self.debugLog(u'Deleting Device' + str(dev.id))
        except Exception as error:
            self.errorLog(u'error within delete panels' + str(error))

    def refreshDataAction(self, valuesDict):
        """
        The refreshDataAction() method refreshes data for all devices based on
        a plugin menu call.
        """
        if self.debugLevel >= 2:
            self.debugLog(u"refreshDataAction() method called.")
        self.refreshData()
        return True

    def refreshData(self):
        """
        The refreshData() method controls the updating of all plugin
        devices.
        """
        if self.debugLevel >= 2:
            self.debugLog(u"refreshData() method called.")

        try:
            # Check to see if there have been any devices created.
            if indigo.devices.iter(filter="self"):
                if self.debugLevel >= 2:
                    self.debugLog(u"Updating data...")

                for dev in indigo.devices.iter(filter="self"):
                    self.refreshDataForDev(dev)

            else:
                indigo.server.log(u"No Enphase Client devices have been created.")

            return True

        except Exception as error:
            self.errorLog(u"Error refreshing devices. Please check settings.")
            self.errorLog(str(error))
            return False

    def checkEnvoyType(self,dev):
        self.logger.debug("Check Envoy Type Called...")
        if self.debugLevel >= 2:
            self.debugLog(u"Type of Envoy Checking...: {0}".format(dev.name))
        data = self.getTheData(dev)
        if "production" in data:
            if len(data['production']) > 1 and int(data['production'][1]['whLifetime']) == 0:
                self.logger.debug("whLifetime Checked: Equals Zero.  Seems Unmetered version.")
                dev.updateStateOnServer('typeEnvoy', value="Unmetered")
                return
            else:
                dev.updateStateOnServer('typeEnvoy', value="Metered")
                self.logger.debug("Envoy-S Metered Version Found.  Continuing.")
                self.parseStateValues(dev, data)
                return
        t.sleep(20)

    def refreshDataForDev(self, dev):
        if dev.configured:
            if self.debugLevel >= 2:
                self.debugLog(u"Found configured device: {0}".format(dev.name))
            if dev.enabled:
                if self.debugLevel >= 2:
                    self.debugLog(u"   {0} is enabled.".format(dev.name))
                timeDifference = int(t.time() - t.mktime(dev.lastChanged.timetuple()))
                if self.debugLevel >= 2:
                    self.debugLog(dev.name + u": Time Since Device Update = " + str(timeDifference))
                    # self.errorLog(str(dev.lastChanged))
                # Get the data.
                # If device is offline wait for 60 seconds until rechecking

                if dev.states['typeEnvoy']== "" or dev.states['typeEnvoy']=="unknown":
                    if self.debugLevel >= 2:
                        self.debugLog(u"Type of Envoy Checking...: {0}".format(dev.name))
                    data = self.getTheData(dev)

                    ## roque test data returns unmetered
                    if data is None:
                        self.logger.debug(u"Data is Nonetype.  Returning.")
                        return

                    if "production" in data:
                        if len(data['production']) > 1 and int( data['production'][1]['whLifetime']) == 0:
                            self.logger.debug("whLifetime Checked: Equals Zero.  Seems Unmetered version.")
                            dev.updateStateOnServer('typeEnvoy', value="Unmetered")
                            return
                        else:
                            dev.updateStateOnServer('typeEnvoy', value="Metered")
                            self.logger.debug("Envoy-S Metered Version Found.  Continuing.")
                            self.parseStateValues(dev, data)
                            return
                    t.sleep(20)
                if dev.states['deviceIsOnline'] == False and timeDifference >= 180:
                    if self.debugLevel >= 2:
                        self.debugLog(u"Offline: Refreshing device: {0}".format(dev.name))
                    data = self.gettheDataChoice(dev)

                    self.parseStateValues(dev, data)
                elif dev.states['deviceIsOnline']:
                    if self.debugLevel >= 2:
                        self.debugLog(u"Online: Refreshing device: {0}".format(dev.name))
                    data = self.gettheDataChoice(dev)
                    self.parseStateValues(dev, data)
            else:
                if self.debugLevel >= 2:
                    self.debugLog(u"    Disabled: {0}".format(dev.name))

    def legacyRefreshEnvoy(self,dev):
        if dev.configured:
            if self.debugLevel >= 2:
                self.debugLog(u"Found configured device: {0}".format(dev.name))

            if dev.enabled:
                if self.debugLevel >= 2:
                    self.debugLog(u"   {0} is enabled.".format(dev.name))
                timeDifference = int(t.time() - t.mktime(dev.lastChanged.timetuple()))
                if self.debugLevel >= 2:
                    self.debugLog(dev.name + u": Time Since Device Update = " + str(timeDifference))
                    # self.errorLog(str(dev.lastChanged))
                # Get the data.
                # If device is offline wait for 60 seconds until rechecking
                if dev.states['deviceIsOnline'] == False and timeDifference >= 180:
                    if self.debugLevel >= 2:
                        self.debugLog(u"Offline: Refreshing device: {0}".format(dev.name))
                    results = self.legacyGetTheData(dev)
                # if device online normal time

                if dev.states['deviceIsOnline']:
                    if self.debugLevel >= 2:
                        self.debugLog(u"Online: Refreshing device: {0}".format(dev.name))
                    results = self.legacyGetTheData(dev)
                    #ignore panel level data until later
                    #self.PanelDict = self.getthePanels(dev)
                    # Put the final values into the device states - only if online
                if dev.states['deviceIsOnline']:
                    self.legacyParseStateValues(dev, results)
            else:
                if self.debugLevel >= 2:
                    self.debugLog(u"    Disabled: {0}".format(dev.name))

    def refreshDataForDevAction(self, valuesDict):
        """
        The refreshDataForDevAction() method refreshes data for a selected device based on
        a plugin menu call.
        """
        if self.debugLevel >= 2:
            self.debugLog(u"refreshDataForDevAction() method called.")

        dev = indigo.devices[valuesDict.deviceId]

        self.refreshDataForDev(dev)
        return True


    def toggleDebugEnabled(self):
        """
        Toggle debug on/off.
        """
        if self.debugLevel >= 2:
            self.debugLog(u"toggleDebugEnabled() method called.")
        if not self.debug:
            self.debug = True
            self.pluginPrefs['showDebugInfo'] = True
            indigo.server.log(u"Debugging on.")
            self.debugLog(u"Debug level: {0}".format(self.debugLevel))

        else:
            self.debug = False
            self.pluginPrefs['showDebugInfo'] = False
            indigo.server.log(u"Debugging off.")
