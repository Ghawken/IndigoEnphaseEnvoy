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
import hashlib
import requests
from urllib.request import urlopen

from urllib.parse import urlsplit
import time
from collections import defaultdict
import os
import shutil
import flatdict
import traceback
from os import path
import re
import random
import logging
import datetime
import threading
from requests.auth import HTTPDigestAuth
import jwt
from authentication import EnphaseTokenManager

import json
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

# Enphase Envoy power production control constants.
# Endpoint and payload structure from the vincentwolsink HA installer integration
# Envoy power production control endpoint and payload values.
# powerForcedOff: 0 = production ON, 1 = production OFF.
ENVOY_POWER_MODE_PATH = "/ivp/mod/603980032/mode/power"
POWER_FORCED_OFF_FALSE = 0  # production enabled
POWER_FORCED_OFF_TRUE = 1   # production disabled
# Enphase Envoy battery/tariff control constants.
# Based on pyenphase (Home Assistant) local API endpoints.
ENVOY_TARIFF_PATH = "/admin/lib/tariff"
ENVOY_GRID_RELAY_PATH = "/ivp/ensemble/relay"
ENVOY_DPEL_PATH = "/ivp/ss/dpel"
PANEL_STALE_THRESHOLD_SECS = 25 * 60  # 15 minutes

class IndigoLogHandler(logging.Handler):
    def __init__(self, display_name: str, level=logging.NOTSET, force_debug: bool = False):

        super().__init__(level)
        self.displayName = display_name
        self.force_debug = force_debug  # if True, always log at DEBUG to Indigo

    def emit(self, record):
        logmessage = ""
        is_error = False
        # Original level from logger
        orig_level = getattr(record, "levelno", logging.INFO)

        # What level Indigo sees
        levelno = logging.DEBUG if self.force_debug else orig_level
        try:
            if self.level <= levelno:
                is_exception = record.exc_info is not None

                if levelno == 5 or levelno == logging.DEBUG:
                    logmessage = "({}:{}:{}): {}".format(
                        path.basename(record.pathname),
                        record.funcName,
                        record.lineno,
                        record.getMessage(),
                    )
                elif levelno == logging.INFO:
                    logmessage = record.getMessage()
                elif levelno == logging.WARNING:
                    logmessage = record.getMessage()
                elif levelno == logging.ERROR:
                    logmessage = "({}: Function: {}  line: {}):    Error :  Message : {}".format(
                        path.basename(record.pathname),
                        record.funcName,
                        record.lineno,
                        record.getMessage(),
                    )
                    is_error = True

                if is_exception:
                    logmessage = "({}: Function: {}  line: {}):    Exception :  Message : {}".format(
                        path.basename(record.pathname),
                        record.funcName,
                        record.lineno,
                        record.getMessage(),
                    )
                    indigo.server.log(message=logmessage, type=self.displayName, isError=is_error, level=levelno)
                    exc = record.exc_info
                    if isinstance(exc, tuple) and len(exc) == 3 and exc[2] is not None:
                        etype, value, tb = exc
                        tb_string = "".join(traceback.format_tb(tb))
                        indigo.server.log(f"Traceback:\n{tb_string}", type=self.displayName, isError=is_error,
                                          level=levelno)
                        indigo.server.log(f"Error in plugin execution:\n\n{traceback.format_exc(30)}",
                                          type=self.displayName, isError=is_error, level=levelno)
                    else:
                        # exc_info may be True/False or missing traceback; don't crash the logger
                        indigo.server.log(f"exc_info present but not a traceback tuple: {exc!r}",
                                          type=self.displayName, isError=is_error, level=levelno)
                    return

                indigo.server.log(message=logmessage, type=self.displayName, isError=is_error, level=levelno)
        except Exception as ex:
            indigo.server.log(f"Error in Logging: {ex}", type=self.displayName, isError=True, level=logging.ERROR)




class Plugin(indigo.PluginBase):
    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        indigo.PluginBase.__init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs)
        self.logger.debug(u"Initializing Enphase plugin.")

        self.session_cache = defaultdict(self._new_session)
        self.force_update = set()  # dev.id values needing immediate refresh

        #self.session = requests.Session()
        self.log_manual_expiry = True
        self.timeOutCount = 0
       # self.debug = self.pluginPrefs.get('showDebugInfo', False)
        self.debugLevel = self.pluginPrefs.get('showDebugLevel', "1")
        if hasattr(self, "indigo_log_handler") and self.indigo_log_handler:
            self.logger.removeHandler(self.indigo_log_handler)

        # Collect everything at logger; handlers filter
        self.logger.setLevel(logging.DEBUG)

        try:
            self.logLevel = int(self.pluginPrefs.get("showDebugLevel", logging.INFO))
            self.fileloglevel = int(self.pluginPrefs.get("showDebugFileLevel", logging.DEBUG))
        except Exception:
            self.logLevel = logging.INFO
            self.fileloglevel = logging.DEBUG
        # Indigo handler for plugin messages (respects user-selected level)
        try:
            self.indigo_log_handler = IndigoLogHandler(pluginDisplayName, level=self.logLevel, force_debug=False)
            self.indigo_log_handler.setFormatter(logging.Formatter("%(message)s"))
            self.logger.addHandler(self.indigo_log_handler)
        except Exception as exc:
            indigo.server.log(f"Failed to create IndigoLogHandler: {exc}", isError=True)

        # File handler
        try:
            self.plugin_file_handler.setLevel(self.fileloglevel)
            # Attach to plugin logger
            self.logger.addHandler(self.plugin_file_handler)
        except Exception as exc:
            self.logger.exception(exc)

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
        self.generated_token = {}  # dev.id -> token string
        self.using_token = False

        self.generated_token_expiry = datetime.datetime.now()
        self.serial_number_full = {}  # dev.id -> full serial
        self.serial_number_last_six = {}  # dev.id -> last 6
        self._cached_panel_extended = {}  # dev.id -> {sn: panel_dict, ...}
        self._freshness_sample_panels = {}  # dev.id -> list[str]
        self._freshness_thread = None       # threading.Thread | None
        self._freshness_stop = threading.Event()

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

        # ── On startup: clear any saved generated tokens from all devices ──
        # This forces a fresh token re-generation on first use, even if the
        # saved token was still valid.  Manual tokens are left untouched.
        # ── On startup: optionally clear any saved generated tokens ──
        # If the user checked "Force clear all generated tokens on next startup"
        # in plugin config, clear them now and reset the flag.
        if self.pluginPrefs.get('forceTokenClear', False):
            self._clear_saved_generated_tokens()
            self.pluginPrefs["forceTokenClear"] = False
            indigo.server.savePluginPrefs()

    def _clear_saved_generated_tokens(self):
        """On plugin startup, remove any saved generated tokens from all Envoy devices.
        This ensures tokens are always re-generated fresh when the plugin starts,
        even if the previously saved token was still valid.
        Manual tokens (use_token mode) are left untouched.
        """
        try:
            for dev in indigo.devices.iter('self'):
                if dev.pluginProps.get("token_source") == "generated" and dev.pluginProps.get("auth_token", ""):
                    self.logger.info(f"Startup: clearing saved generated token for device '{dev.name}' — will re-generate.")
                    localProps = dev.pluginProps
                    localProps["auth_token"] = ""
                    localProps["token_source"] = ""

                    dev.replacePluginPropsOnServer(localProps)

        except Exception:
            self.logger.debug("Could not clear saved tokens on startup.", exc_info=True)

    def _new_session(self):
        """Create a fresh requests.Session with keep-alive and TLS disabled."""
        s = requests.Session()
        s.verify = False  # keep skipping TLS validation
        s.headers.update({"Connection": "keep-alive"})
        return s

    # ─────────────────────────────────────────────────────────────
    # ─────────────────────────────────────────────────────────────
    # Generic GET  – headers mandatory, auth optional, detailed logging
    # ─────────────────────────────────────────────────────────────
    def _get(self, url, *, headers, timeout=35, auth=None, **kwargs):
        """
        Fetch *url* with a per-host Session, emitting DEBUG logs that show
        whether we are creating or re-using the session for this host.
        """
        try:
            host = urlsplit(url).netloc  # e.g. "192.168.1.50"
            is_new = host not in self.session_cache  # defaultdict check *before* lookup
            session = self.session_cache[host]  # auto-creates if missing

            # ── session creation / reuse info ───────────────────────
            if is_new:
                self.logger.debug(
                    f"[HTTP] Created NEW session {hex(id(session))} for host {host}"
                )
            else:
                self.logger.debug(
                    f"[HTTP] Re-using session {hex(id(session))} for host {host}"
                )

            # ── outgoing request details ────────────────────────────
            self.logger.debug(
                f"[HTTP] GET {url}\n"
                f"       timeout={timeout!r}  auth={'YES' if auth else 'NO'}\n"
                f"       headers={headers}\n"
                f"       cookies={session.cookies.get_dict()}"
            )

            try:
                resp = session.get(
                    url,
                    headers=headers,
                    timeout=timeout,
                    auth=auth,
                    allow_redirects=True,
                    **kwargs
                )

                self.logger.debug(
                    f"[HTTP] {host} → {resp.status_code}  "
                    f"(session {hex(id(session))})"
                )
                return resp

            except requests.exceptions.Timeout as err:
                self.logger.debug(
                    f"[HTTP] TIMEOUT for host {host}: {err} — "
                    f"closing session {hex(id(session))} and recreating"
                )
                session.close()
                self.session_cache[host] = self._new_session()
                self.WaitInterval = 60
                raise

            except requests.exceptions.RequestException as err:
                # ── connection/TLS error; drop pool and log ─────────
                self.logger.debug(
                    f"[HTTP] ERROR for host {host}: {err} — "
                    f"closing session {hex(id(session))} and recreating"
                )
                session.close()
                self.session_cache[host] = self._new_session()
                raise

        except Exception as err:
            self.logger.debug(f"Exception in _get {err}")
            raise

    def __del__(self):
        self.logger.debug(u"__del__ method called.")
        indigo.PluginBase.__del__(self)

    def validateDeviceConfigUi(self, valuesDict, typeId, devId):
        try:
            self.logger.debug(f"validateDeviceConfigUi called for devId {devId}")
            dev = indigo.devices[devId]
            old_generate_token = dev.pluginProps.get("generate_token", False)
            new_generate_token = valuesDict.get("generate_token", False)
            # Token mode changed — reset token_source so the new mode starts
            # cleanly.  auth_token is left as-is: if the user pasted a new
            # manual token it is already in valuesDict; if they didn't, the
            # old (generated) token can still serve until they replace it.
            # The runtime cache (self.generated_token) is cleared separately
            # in deviceStartComm which runs after this dialog closes.
            if old_generate_token != new_generate_token:
                self.logger.info(
                    f"Token mode changed (generate_token: {old_generate_token} → {new_generate_token}) "
                    f"— resetting token_source."
                )
                valuesDict["token_source"] = ""
            # Credentials changed while in generate-token mode — force a
            # fresh token so an owner→installer switch takes effect
            # immediately instead of re-using the old cached token.
            if new_generate_token:
                old_user = dev.pluginProps.get("enphase_user", "")
                old_pass = dev.pluginProps.get("enphase_password", "")
                new_user = valuesDict.get("enphase_user", "")
                new_pass = valuesDict.get("enphase_password", "")
                if old_user != new_user or old_pass != new_pass:
                    self.logger.info(
                        f"Enphase credentials changed — clearing saved token to force re-generation."
                    )
                    valuesDict["token_source"] = ""
                    valuesDict["auth_token"] = ""

            return (True, valuesDict)
        except Exception:
            self.logger.debug("validateDeviceConfigUi error", exc_info=True)
            return (True, valuesDict)


    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        self.logger.debug(u"closedPrefsConfigUi() method called.")

        if userCancelled:
            self.logger.debug(u"User prefs dialog cancelled.")

        if not userCancelled:
            self.debug = valuesDict.get('showDebugInfo', False)
            self.debugLevel = self.pluginPrefs.get('showDebugLevel', "1")
            self.logger.debug(u"User prefs saved.")

            self.pluginPrefs["showDebugInfo"] = bool(valuesDict.get("showDebugInfo", False))
            self.pluginPrefs["showDebugLevel"] = int(valuesDict.get("showDebugLevel", logging.INFO))
            self.pluginPrefs["showDebugFileLevel"] = int(valuesDict.get("showDebugFileLevel", logging.DEBUG))

            self.logLevel = int(valuesDict.get("showDebugLevel", logging.INFO))
            self.fileloglevel = int(valuesDict.get("showDebugFileLevel", logging.DEBUG))
            show_lib_debug = bool(valuesDict.get("showDebugInfo", False))
            if hasattr(self, "indigo_log_handler") and self.indigo_log_handler:
                self.indigo_log_handler.setLevel(self.logLevel)
            if hasattr(self, "plugin_file_handler") and self.plugin_file_handler:
                self.plugin_file_handler.setLevel(self.fileloglevel)
            indigo.server.savePluginPrefs()
            self.debugupdate = valuesDict.get('debugupdate', False)
            self.openStore = valuesDict.get('openStore', False)

            if self.debug:
                indigo.server.log(u"Debugging on (Level: {0})".format(self.debugLevel))
            else:
                indigo.server.log(u"Debugging off.")

            if int(self.pluginPrefs['showDebugLevel']) >= 3:
                self.logger.debug(u"valuesDict: {0} ".format(valuesDict))

        return True

    # Start 'em up.
    def deviceStartComm(self, dev):
 #
 #      self.logger.debug(u"deviceStartComm() method called.")
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


        if dev.deviceTypeId == 'EnphaseEnvoyBatteryDevice':
            self.logger.info(u"Starting Enphase Battery & Grid device: " + dev.name)
            dev.setErrorStateOnServer(None)

        #number_Panels = 0
        #numer_Panels = indigo.devices.len(filter='self.EnphasePanelDevice')
        indigo.server.log(u"Starting Enphase/Envoy device: " + dev.name )
        dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)

        dev.updateStateOnServer('deviceIsOnline', value=True, uiValue="Online")

        self.generated_token.pop(dev.id, None)
    # Also clear persisted generated token so that credential changes
    # (e.g. owner → installer) take effect immediately instead of
    # re-using the old cached token until it expires.


        if dev.pluginProps.get("token_source") == "generated" and dev.pluginProps.get("auth_token", ""):
            localProps = dev.pluginProps
            localProps["auth_token"] = ""
            localProps["token_source"] = ""
            #dev.replacePluginPropsOnServer(localProps)

        self.log_manual_expiry = True
        self.force_update.add(dev.id)

        dev.stateListOrDisplayStateIdChanged()



# Default Indigo Plugin StateList
# This overrides and pulls the current state list (from devices.xml and then adds whatever to it via these calls
# http://forums.indigodomo.com/viewtopic.php?f=108&t=12898
# for summary
# Issue being that with trigger and control page changes will add the same to all devices unless check what device within below call - should be an issue for this plugin
# """"
#     def getDeviceStateList(self,dev):
#         if self.debugLevel>=2:
#             self.logger.debug(u'getDeviceStateList called')
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
        self.logger.debug(u"deviceStopComm() method called.")
        self.logger.debug(u"Stopping Enphase device: " + dev.name + " and id:"+str(dev.model))
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
                self.logger.debug(u'Quick Checks Before Loop')
            if dev.enabled:
                self.refreshDataForDev(dev)
                self.sleep(30)
                self.checkPanelInventory(dev)
                self.sleep(30)
                self.checkThePanels_New(dev)
                self.sleep(10)
        return

    def get_enphasetoken(self, username, password, serialnumber, dev):
        """
        Fetch a valid Enphase token using pyenphase-style logic (like HA).
        - Uses cached/manual token if present (device/plugin prefs)
        - Refreshes token when near expiry or missing (requires cloud username/password + serial)
        - If refresh succeeds, persist the new token
        """
        try:
            self.logger.info(
                "Obtaining Enphase token (pyenphase). "
                "A valid token is typically needed for local Envoy API access."
            )

            # 1) Get any existing token you may already have stored
            # Prefer device plugin props if you store per-device; otherwise pluginPrefs.
            existing_token = None
            try:
                # If dev is an Indigo device, you might be storing token in pluginProps:
                # existing_token = dev.pluginProps.get("enphase_token")
                # If not, fall back to pluginPrefs:
                existing_token = dev.pluginPrefs.get("auth_token")
            except Exception:
                existing_token = None

            # 2) Determine Envoy host/ip from the device if you have it
            # (Adjust this to however you store the Envoy IP/hostname)
            try:
                envoy_host = dev.pluginProps.get("sourceXML")
            except Exception:
                envoy_host = getattr(dev, "sourceXML", None)

            if not envoy_host:
                self.logger.info("Please setup IP address of Device")
                return

            # 3) Create token manager
            tm = EnphaseTokenManager(
                host=envoy_host,
                cloud_username=username,
                cloud_password=password,
                envoy_serial=serialnumber,
                token=existing_token,
                logger=self.logger,
                # refresh when within 7 days of expiry (tune as desired)
                refresh_margin_seconds=7 * 24 * 3600,
                timeout_seconds=60,
            )

            # 4) Get token (refreshes only if needed)
            token_raw = tm.get_token()

            if not token_raw or not token_raw.strip():
                raise Exception("No token returned from token manager.")

            # 6) Do NOT log full token
            self.logger.debug(f"Enphase token ready {token_raw})")
            self.generated_token[dev.id] = token_raw
            self._log_token_info(token_raw, dev, source="newly generated")
            localPropsCopy = dev.pluginProps
            localPropsCopy["auth_token"] = token_raw
            localPropsCopy["token_source"] = "generated"
            dev.replacePluginPropsOnServer(localPropsCopy)

            return token_raw

        except Exception:
            self.logger.debug("Exception getting token:", exc_info=True)
            return None
###
##
    # ── Power Production Control ────────────────────────────────────────

    def enablePowerProduction(self, pluginAction):
        """Action callback: enable power production for the selected device."""
        dev = indigo.devices[pluginAction.deviceId]
        self._setPowerProduction(dev, enable=True)

    def disablePowerProduction(self, pluginAction):
        """Action callback: disable power production for the selected device."""
        dev = indigo.devices[pluginAction.deviceId]
        self._setPowerProduction(dev, enable=False)

    def _pollPowerProductionStatus(self, dev):
        """
        Poll the Envoy power production endpoint to keep the
        powerProductionEnabled state in sync.

        Reads 'powerForcedOff' from /ivp/mod/603980032/mode/power.
        Only runs when an auth token is available (firmware 7.x+).
        If the token is not installer-level the endpoint returns 401/403
        and the device state is set to 'N/A – Installer Token Required'.
        """
        headers = self.create_headers(dev)
        if not headers:
            return

        ip_address = dev.pluginProps.get('sourceXML', '')
        if not ip_address:
            return

        url = f"http{self.https_flag}://{ip_address}{ENVOY_POWER_MODE_PATH}"

        try:
            r = self._get(url, headers=headers)
            if r.status_code == 200:
                data = r.json()
                power_forced_off = data.get('powerForcedOff')
                if power_forced_off is not None:
                    production_enabled = (power_forced_off == POWER_FORCED_OFF_FALSE)
                    dev.updateStateOnServer('powerProductionEnabled',
                                                value="Enabled" if production_enabled else "Disabled")
                    if self.debugLevel >= 2:
                        self.logger.debug(f"Power production status polled: enabled={production_enabled}")
            elif r.status_code in (401, 403):
                dev.updateStateOnServer('powerProductionEnabled',
                                        value="Status Unavailable")
                if self.debugLevel >= 1:
                    self.logger.debug(
                        f"Cannot poll power production status for {dev.name}. "
                        f"HTTP {r.status_code}. "
                        f"This endpoint requires an installer-level JWT token."
                    )
            else:
                if self.debugLevel >= 2:
                    self.logger.debug(f"Could not poll power production status. HTTP {r.status_code}")
        except Exception as err:
            if self.debugLevel >= 2:
                self.logger.debug(f"Error polling power production status: {err}")

    def _pollDpelStatus(self, dev):
        """
        Poll the DPEL (Dynamic Power Export Limiting) endpoint to keep
        dpelEnabled and dpelLimitWatts states in sync.

        Reads from GET /ivp/ss/dpel (installer token required).
        """
        if not self._is_installer_token(dev):
            return

        headers = self.create_headers(dev)
        if not headers:
            return

        ip_address = dev.pluginProps.get('sourceXML', '')
        if not ip_address:
            return

        url = f"http{self.https_flag}://{ip_address}{ENVOY_DPEL_PATH}"

        try:
            r = self._get(url, headers=headers)
            if r.status_code == 200:
                data = r.json()
                dpel_settings = data.get('dynamic_pel_settings', {})
                enabled = dpel_settings.get('enable', False)
                limit_w = dpel_settings.get('limit_value_W', 0)
                export_limit = dpel_settings.get('export_limit', True)

                mode_label = "Export" if export_limit else "Production"
                if enabled:
                    dev.updateStateOnServer('dpelEnabled',
                                            value=f"Enabled ({mode_label} Limit)")
                else:
                    dev.updateStateOnServer('dpelEnabled', value="Disabled")
                dev.updateStateOnServer('dpelLimitWatts', value=float(limit_w))

                if self.debugLevel >= 2:
                    self.logger.debug(
                        f"DPEL status polled: enabled={enabled}, limit={limit_w}W, mode={mode_label}"
                    )
            elif r.status_code in (401, 403):
                dev.updateStateOnServer('dpelEnabled', value="Status Unavailable")
                if self.debugLevel >= 1:
                    self.logger.debug(
                        f"Cannot poll DPEL status for {dev.name}. HTTP {r.status_code}. "
                        f"This endpoint requires an installer-level JWT token."
                    )
            else:
                if self.debugLevel >= 2:
                    self.logger.debug(f"Could not poll DPEL status. HTTP {r.status_code}")
        except Exception as err:
            if self.debugLevel >= 2:
                self.logger.debug(f"Error polling DPEL status: {err}")

    def _fetchPollingInterval(self, dev):
        """
        Fetch the Envoy's internal polling/scan interval from /ivp/peb/newscan.
        Requires an installer-level token.  Called once at startup; stores the
        result in the envoyPollingInterval device state.
        """
        if not self._is_installer_token(dev):
            self.logger.debug(f"[{dev.name}] Skipping polling interval fetch — not an installer token.")
            return
        headers = self.create_headers(dev)
        if not headers:
            return
        ip_address = dev.pluginProps.get('sourceXML', '')
        if not ip_address:
            return
        url = f"http{self.https_flag}://{ip_address}/ivp/peb/newscan"
        try:
            r = self._get(url, headers=headers)
            if r.status_code == 200:
                data = r.json()
                # Response is {"newDeviceScan": {"polling-period-secs": 900, ...}}
                interval = 0
                if isinstance(data, dict):
                    scan_data = data.get('newDeviceScan', data)
                    if isinstance(scan_data, dict):
                        interval = scan_data.get('polling-period-secs',
                                       scan_data.get('period',
                                       scan_data.get('interval', 0)))
                    else:
                        interval = 0
                elif isinstance(data, (int, float)):
                    interval = int(data)
                dev.updateStateOnServer('envoyPollingInterval', value=int(interval))
                self.logger.info(f"[{dev.name}] Envoy polling interval: {interval}s")
            elif r.status_code in (401, 403):
                self.logger.debug(
                    f"[{dev.name}] Cannot fetch polling interval — HTTP {r.status_code}. "
                    f"Requires installer-level token."
                )
            else:
                self.logger.debug(f"[{dev.name}] Polling interval endpoint returned HTTP {r.status_code}")
        except Exception as err:
            self.logger.debug(f"[{dev.name}] Error fetching polling interval: {err}")



    def _enableDpel(self, dev, watts, slew_rate=50.0, export_limit=True):
        """
        Enable DPEL (Dynamic Power Export Limiting) via POST /ivp/ss/dpel.
        Requires an installer-level JWT token.

        Based on the vincentwolsink HA integration's enable_dpel method.
        """
        headers = self.create_headers(dev)
        if not headers:
            self.logger.error(
                f"No auth token configured for device: {dev.name}. "
                f"An installer-level JWT token is required for DPEL control."
            )
            return False

        ip_address = dev.pluginProps.get('sourceXML', '')
        if not ip_address:
            self.logger.error(f"No IP address configured for device: {dev.name}")
            return False

        url = f"http{self.https_flag}://{ip_address}{ENVOY_DPEL_PATH}"
        payload = json.dumps({
            "dynamic_pel_settings": {
                "enable": True,
                "export_limit": export_limit,
                "limit_value_W": float(watts),
                "slew_rate": float(slew_rate),
                "enable_dynamic_limiting": False,
            },
            "filename": "site_settings",
            "version": "00.00.01",
        })
        headers['Content-Type'] = 'application/json'

        try:
            if self.debugLevel >= 2:
                self.logger.debug(f"Enabling DPEL for: {dev.name} ({watts}W)")

            host = urlsplit(url).netloc
            session = self.session_cache[host]
            r = session.post(url, data=payload, headers=headers,
                             timeout=self.prefServerTimeout, allow_redirects=True)

            if r.status_code in (200, 204):
                mode_label = "Export" if export_limit else "Production"
                indigo.server.log(
                    f"DPEL enabled for {dev.name}: {watts}W {mode_label} limit"
                )
                dev.updateStateOnServer('dpelEnabled',
                                        value=f"Enabled ({mode_label} Limit)")
                dev.updateStateOnServer('dpelLimitWatts', value=float(watts))
                return True
            elif r.status_code in (401, 403):
                self.logger.info(
                    f"Authorization failed enabling DPEL for {dev.name}. "
                    f"HTTP {r.status_code}. "
                    f"This endpoint requires an installer-level JWT token."
                )
                return False
            else:
                self.logger.error(
                    f"Failed to enable DPEL for {dev.name}. "
                    f"HTTP {r.status_code}: {r.text}"
                )
                return False

        except requests.exceptions.Timeout:
            self.logger.error(f"Timeout enabling DPEL for: {dev.name}")
            return False
        except requests.exceptions.ConnectionError:
            self.logger.error(f"Connection error enabling DPEL for: {dev.name}")
            return False
        except Exception as err:
            self.logger.error(f"Error enabling DPEL for {dev.name}: {err}")
            return False

    def _disableDpel(self, dev):
        """
        Disable DPEL (Dynamic Power Export Limiting) via POST /ivp/ss/dpel.
        Requires an installer-level JWT token.

        Based on the vincentwolsink HA integration's disable_dpel method.
        """
        headers = self.create_headers(dev)
        if not headers:
            self.logger.error(
                f"No auth token configured for device: {dev.name}. "
                f"An installer-level JWT token is required for DPEL control."
            )
            return False

        ip_address = dev.pluginProps.get('sourceXML', '')
        if not ip_address:
            self.logger.error(f"No IP address configured for device: {dev.name}")
            return False

        url = f"http{self.https_flag}://{ip_address}{ENVOY_DPEL_PATH}"
        payload = json.dumps({
            "dynamic_pel_settings": {"enable": False},
            "filename": "site_settings",
            "version": "00.00.01",
        })
        headers['Content-Type'] = 'application/json'

        try:
            if self.debugLevel >= 2:
                self.logger.debug(f"Disabling DPEL for: {dev.name}")

            host = urlsplit(url).netloc
            session = self.session_cache[host]
            r = session.post(url, data=payload, headers=headers,
                             timeout=self.prefServerTimeout, allow_redirects=True)

            if r.status_code in (200, 204):
                indigo.server.log(f"DPEL disabled for {dev.name}")
                dev.updateStateOnServer('dpelEnabled', value="Disabled")
                return True
            elif r.status_code in (401, 403):
                self.logger.info(
                    f"Authorization failed disabling DPEL for {dev.name}. "
                    f"HTTP {r.status_code}. "
                    f"This endpoint requires an installer-level JWT token."
                )
                return False
            else:
                self.logger.error(
                    f"Failed to disable DPEL for {dev.name}. "
                    f"HTTP {r.status_code}: {r.text}"
                )
                return False

        except requests.exceptions.Timeout:
            self.logger.error(f"Timeout disabling DPEL for: {dev.name}")
            return False
        except requests.exceptions.ConnectionError:
            self.logger.error(f"Connection error disabling DPEL for: {dev.name}")
            return False
        except Exception as err:
            self.logger.error(f"Error disabling DPEL for {dev.name}: {err}")
            return False

    def enableDpelAction(self, pluginAction):
        """Action callback: enable DPEL for the selected device."""
        dev = indigo.devices[pluginAction.deviceId]
        try:
            watts = float(pluginAction.props.get('dpelWatts', 0))
        except (ValueError, TypeError):
            self.logger.error("Invalid DPEL watt value. Must be a number.")
            return
        try:
            slew_rate = float(pluginAction.props.get('dpelSlewRate', 50))
        except (ValueError, TypeError):
            slew_rate = 50.0
        export_limit = pluginAction.props.get('dpelExportLimit', True)
        # ConfigUI checkbox returns string 'true'/'false'
        if isinstance(export_limit, str):
            export_limit = export_limit.lower() == 'true'
        self.logger.info(f"Enabling DPEL for {dev.name}: {watts}W, slew={slew_rate}, export_limit={export_limit}")
        self._enableDpel(dev, watts, slew_rate, export_limit)

    def disableDpelAction(self, pluginAction):
        """Action callback: disable DPEL for the selected device."""
        dev = indigo.devices[pluginAction.deviceId]
        self.logger.info(f"Disabling DPEL for {dev.name}")
        self._disableDpel(dev)

    def _setPowerProduction(self, dev, enable):
        """
        Enable or disable solar power production via the Envoy local API.

        Uses PUT /ivp/mod/603980032/mode/power.
        Requires an installer-level JWT token (firmware 7.x+) configured
        via the existing auth_token device property.
        """
        headers = self.create_headers(dev)
        if not headers:
            self.logger.error(
                f"No auth token configured for device: {dev.name}. "
                f"An installer-level JWT token is required for power production control."
            )
            return False

        ip_address = dev.pluginProps.get('sourceXML', '')
        if not ip_address:
            self.logger.error(f"No IP address configured for device: {dev.name}")
            return False

        power_forced_off = POWER_FORCED_OFF_FALSE if enable else POWER_FORCED_OFF_TRUE
        url = f"http{self.https_flag}://{ip_address}{ENVOY_POWER_MODE_PATH}"
        # The Envoy expects a JSON array payload: 'arr' holds one element per
        # inverter group, and 'length' is the count of elements.  A single-element
        # array controls the whole site.  0 = production on, 1 = production off.
        payload = json.dumps({"length": 1, "arr": [power_forced_off]})
        headers['Content-Type'] = 'application/json'

        action_label = "Enabling" if enable else "Disabling"

        try:
            if self.debugLevel >= 2:
                self.logger.debug(f"{action_label} power production for: {dev.name}")
                self.logger.debug(f"PUT {url}")

            host = urlsplit(url).netloc
            session = self.session_cache[host]
            r = session.put(url, data=payload, headers=headers,
                            timeout=self.prefServerTimeout, allow_redirects=True)

            if r.status_code in (200, 204):
                indigo.server.log(
                    f"Power production {'enabled' if enable else 'disabled'} for {dev.name}"
                )
                dev.updateStateOnServer('powerProductionEnabled', value="Enabled")
                return True
            elif r.status_code in (401, 403):
                self.logger.info(
                    f"Authorization failed {action_label.lower()} power production for {dev.name}. "
                    f"HTTP {r.status_code}. "
                    f"This endpoint requires an installer-level JWT token. "
                    f"Please update the auth token in the device configuration."
                )
                dev.updateStateOnServer('powerProductionEnabled',
                                       value="Status Unavailable")
                return False
            else:
                self.logger.error(
                    f"Failed to {action_label.lower()} power production for {dev.name}. "
                    f"HTTP {r.status_code}: {r.text}"
                )
                return False

        except requests.exceptions.Timeout:
            self.logger.error(f"Timeout {action_label.lower()} power production for: {dev.name}")
            return False
        except requests.exceptions.ConnectionError:
            self.logger.error(f"Connection error {action_label.lower()} power production for: {dev.name}")
            return False
        except Exception as err:
            self.logger.error(f"Error {action_label.lower()} power production for {dev.name}: {err}")
            return False


###########
    def _get_enphase_token_expiry(self, token):
        try:
            payload = jwt.decode(token, options={"verify_signature": False})
            return int(payload.get("exp")) if payload.get("exp") else None
        except Exception:
            return None

    def _is_enphase_token_expired(self, token):
        try:
            decode = jwt.decode( token, options={"verify_signature": False}, algorithms="ES256"  )
            exp_epoch = decode["exp"]
            self.logger.debug(f"Decoded Token:\n{decode}")
            # allow a buffer so we can try and grab it sooner
            exp_epoch -= 900
            exp_time = datetime.datetime.fromtimestamp(exp_epoch)
            self.generated_token_expiry = exp_time
            # refresh 5 minutes before actual expiry to avoid failed requests
            refresh_time = datetime.datetime.fromtimestamp(exp_epoch - 300)
            if datetime.datetime.now() < refresh_time:
                self.logger.debug("Enphase Token expires at: %s", exp_time)
                return False
            else:
                self.logger.debug("Enphase Token expiring soon/expired (actual expiry: %s) — refreshing proactively", exp_time)
                return True
        except:
            self.logger.exception("Exception with check expired token.  Perhaps Crytography not installed?")
            return False

    def _get_token_type(self, token):
        """Return the enphaseUser field from the JWT payload ('owner' or 'installer'), or 'unknown'."""
        try:
            payload = jwt.decode(token, options={"verify_signature": False})
            return payload.get("enphaseUser", "unknown")
        except Exception:
            return "unknown"

    def _log_token_info(self, token, dev, source=""):
        """Log token type (owner/installer), expiry, and source prominently."""
        token_type = self._get_token_type(token)
        exp = self._get_enphase_token_expiry(token)
        exp_str = datetime.datetime.fromtimestamp(exp).strftime("%c") if exp else "unknown"
        prefix = f"[{dev.name}]"
        source_str = f" ({source})" if source else ""
        self.logger.info(
            f"{prefix} Enphase Token Type: ** {token_type.upper()} **{source_str}  —  Expires: {exp_str}"
        )
        if token_type == "installer":
            self.logger.info(f"{prefix} Installer token detected — full Envoy API access including power control.")
        elif token_type == "owner":
            self.logger.info(f"{prefix} Owner/Homeowner token detected — read-only data access. Power control endpoints will not be available.")
        else:
            self.logger.warning(f"{prefix} Could not determine token type from JWT payload.")

    def check_endpoints(self, valuesDict, typeId, devId):
        self.logger.info("Checking endpoints.")
        end_thread = threading.Thread(target=self.thread_endpoints, args=[valuesDict, typeId, devId])
        end_thread.start()

########### Get Installer Password
    def installer_password(self, valuesDict, typeId, devId):
        self.logger.info("Checking endpoints.")
        dev = indigo.devices[devId]
        gSerialNumber = self.serial_number_full.get(dev.id,"").encode("utf-8")
        if len(gSerialNumber) <2:
            self.logger.info(f"Serial Number : {gSerialNumber} appears incorrect")
            return

        realm = b'enphaseenergy.com'
        userName = b'installer'

        digest =  hashlib.md5(b'[e]' + userName + b'@' + realm + b'#' + gSerialNumber + b' EnPhAsE eNeRgY ').hexdigest()
        countZero = digest.count('0')
        countOne = digest.count('1')
        password = ''
        for cc in digest[::-1][:8]:
            if countZero == 3 or countZero == 6 or countZero == 9:
                countZero = countZero - 1
            if countZero > 20:
                countZero = 20
            if countZero < 0:
                countZero = 0

            if countOne == 9 or countOne == 15:
                countOne = countOne - 1
            if countOne > 26:
                countOne = 26
            if countOne < 0:
                countOne = 0
            if cc == '0':
                password += chr(ord('f') + countZero)
                countZero = countZero - 1
            elif cc == '1':
                password += chr(ord('@') + countOne)
                countOne = countOne - 1
            else:
                password += cc
        self.logger.info(f"Installer Password:\n {password}")

    def thread_endpoints(self, valuesDict, typeId, devId):
       # delete all panel devices first up
        self.logger.info(f"Checking all possible Endpoints...")
        self.logger.info(f"Pausing usual updates for 3 minutes")
        #self.logger.debug(f"valueDict {valuesDict}")
        dev = indigo.devices[devId]
        sourceip = valuesDict["sourceXML"]
        self.WaitInterval = 360
        endpoints = [ "http{}://{}/ivp/pdm/energy",
                      "http{}://{}/ivp/pdm/production",
            "http{}://{}/production.json",
                      "http{}://{}/production",
                      "http{}://{}/inventory.json",
                      "http{}://{}/api/v1/production",
                      "http{}://{}/api/v1/production/inverters",
                      "http{}://{}/auth/check_jwt",
                      "http{}://{}/ivp/meters",
                      "http{}://{}/ivp/meters/readings",
                      "http{}://{}/ivp/ensemble/inventory",
                      "http{}://{}/ivp/livedata/status",
                      "http{}://{}/ivp/peb/devstatus",
                      "http{}://{}/ivp/ss/dpel",
                      "http{}://{}/ivp/meters/reports/consumption",
                      "http{}://{}/info.xml"
                      ]
        success = []
        https_flag = "s"
        for endpoint in endpoints:
            url = endpoint.format(https_flag, sourceip)
            try:
                self.sleep(2)
                self.logger.info(f"Trying Endpoint:{url}")
                headers = self.create_headers(dev)
                response = requests.get(url, timeout=25,verify=False,  headers=headers, allow_redirects=False)
                if response.status_code == 200:
                    self.logger.info(f"Success:  {url}")
                    self.logger.info(f"Response: {response.json()}")
                else:
                    self.logger.info(f"Failed, Response Code  {response.status_code}")
                    self.logger.debug(f"Response: {response}")
            except Exception as ex:
                self.logger.debug(f"Failed.  Exception: {ex}")
            self.logger.debug("---------------------------------")
        https_flag = ""
        for endpoint in endpoints:
            url = endpoint.format(https_flag, sourceip)
            try:
                self.sleep(2)
                self.logger.info(f"Trying Endpoint:{url}")
                headers = self.create_headers(dev)
                response = requests.get(url, timeout=25, verify=False, headers=headers, allow_redirects=False)
                if response.status_code == 200:
                    self.logger.info(f"Success:  {url}")
                    self.logger.info(f"Response: {response.json()}")
                else:
                    self.logger.info(f"Failed, Response Code  {response.status_code}")
                    self.logger.debug(f"Response: {response}")
            except Exception as ex:
                self.logger.debug(f"Failed.  Exception: {ex}")

        self.logger.info(" ------- End of Check Endpoints -------")
        self.WaitInterval = 0


        return

    def runConcurrentThread(self):

        # ─────────────────────────────────────────────────────────
        # Constants
        # ─────────────────────────────────────────────────────────
        NOW = time.monotonic  # immune to NTP/DST jumps

        CHECKS = {  # cadence in seconds
            "datetime": 22 * 60,  # 22 min
            "envoy_type": 6 * 60 * 60,  # 6 h
            "panel_inventory": 5 * 60,  # 5 min
            "panel_health": 60,  # 3 min 20 s
            "panel_extended": 15 * 60,  # 15 min – extended data (voltage, temp, etc.)
            "envoy_refresh": 60,  # 1 min
         #   "freshness_check": 60,  # 1 min – diagnostic: compare endpoint freshness
        }

        # timers[dev.id][check_name] → last-run timestamp
        timers = defaultdict(lambda: defaultdict(lambda: NOW()))
        enabled_state = {}  # dev.id -> last enabled bool

        # ─────────────────────────────────────────────────────────
        # Helper: run-and-reset
        # ─────────────────────────────────────────────────────────
        def _run_check(ts, key, period, func, *args):
            """
            Run `func` when its period has elapsed.

            • Timer is bumped *before* the call so a failure
              does NOT cause an immediate retry.
            • Any exception is logged; probe will try again
              after the normal interval.
            """
            now = NOW()
            if now - ts[key] >= period:
                ts[key] = now  # ← advance timer first
                try:
                    func(*args)
                except Exception:
                    self.logger.exception(
                        f"{func.__name__} failed for {args[0].name} – will retry in {period}s"
                    )

        try:
            # ── One-off startup refresh ─────────────────────────
            for dev in indigo.devices.iter('self.EnphaseEnvoyDevice'):
                if dev.enabled:
                    self.refreshDataForDev(dev)
                    self.sleep(5)
                    # One-time: fetch Envoy polling interval from /ivp/peb/newscan
                    try:
                        self._fetchPollingInterval(dev)
                    except Exception:
                        self.logger.debug("Could not fetch polling interval at startup.", exc_info=True)

            for dev in indigo.devices.iter('self.EnphaseEnvoyLegacy'):
                if dev.enabled:
                    self.legacyRefreshEnvoy(dev)
                    self.sleep(5)

            # ── Main loop ───────────────────────────────────────
            while True:

                # Modern Envoy devices
                for dev in indigo.devices.iter('self.EnphaseEnvoyDevice'):
                    if not dev.enabled:
                        continue

                        # If device was just enabled, force immediate checks
                    if enabled_state.get(dev.id) is not True:
                        enabled_state[dev.id] = True
                        ts = timers[dev.id]
                        for k in CHECKS:
                            ts[k] = 0

                    ts = timers[dev.id]
                    # Force immediate update after stop/start or device restart
                    if dev.id in self.force_update:
                        for k in CHECKS:
                            ts[k] = 0
                        self.force_update.discard(dev.id)

                    _run_check(ts, "datetime", CHECKS["datetime"], self.checkDayTime, dev)
                    _run_check(ts, "envoy_type", CHECKS["envoy_type"], self.checkEnvoyType, dev)
                    _run_check(ts, "panel_inventory", CHECKS["panel_inventory"], self.checkPanelInventory, dev)
                    _run_check(ts, "panel_extended", CHECKS["panel_extended"], self._refreshPanelExtendedData, dev)
                    _run_check(ts, "panel_health", CHECKS["panel_health"], self.checkThePanels_New, dev)
                    _run_check(ts, "envoy_refresh", CHECKS["envoy_refresh"], self.refreshDataForDev, dev)
                  #  _run_check(ts, "freshness_check", CHECKS["freshness_check"], self._compare_panel_freshness, dev)
                    self.sleep(1)  # small yield between devices

                # Legacy Envoy devices
                for dev in indigo.devices.iter('self.EnphaseEnvoyLegacy'):
                    if not dev.enabled:
                        enabled_state[dev.id] = False
                        continue

                    if enabled_state.get(dev.id) is not True:
                        enabled_state[dev.id] = True
                        timers[dev.id]["envoy_refresh"] = 0

                    ts = timers[dev.id]
                    if dev.id in self.force_update:
                        ts["envoy_refresh"] = 0
                        self.force_update.discard(dev.id)
                    _run_check(ts, "envoy_refresh", CHECKS["envoy_refresh"], self.legacyRefreshEnvoy, dev)
                    self.sleep(1)

                # ── Global back-off if another routine requested it ──
                if self.WaitInterval > 0:
                    self.logger.debug(f"Back-off requested: sleeping {self.WaitInterval} s")
                    self.sleep(self.WaitInterval)
                    self.WaitInterval = 0

                    # After a forced wait, bump only short-cadence checks
                    now = NOW()
                    for ts in timers.values():
                        ts["panel_inventory"] = now
                        ts["panel_health"] = now
                        ts["panel_extended"] = now
                        ts["envoy_refresh"] = now
                    # Leave "envoy_type" and "datetime" untouched → cadence preserved

                self.sleep(25)  # base loop delay

        except self.StopThread:
            self.logger.debug("Stopping Enphase/Envoy thread.")
        except Exception:
            self.logger.exception("Unhandled exception in Enphase/Envoy thread")
            self.WaitInterval = 60

    # ─────────────────────────────────────────────────────────────
    # On-demand diagnostic: compare per-inverter timestamps across
    # all 3 endpoints.  Triggered from the Plugin menu; runs in its
    # own thread for ≤15 minutes, polling every 60 s.
    # ─────────────────────────────────────────────────────────────
    def startFreshnessCheck(self):
        """Menu callback – start the panel freshness diagnostic.

        Iterates all enabled EnphaseEnvoyDevice devices that have
        ``activatePanels`` turned on.  A single background thread is
        created; it runs for up to 15 minutes (or until
        ``stopFreshnessCheck`` is called).
        """
        if self._freshness_thread is not None and self._freshness_thread.is_alive():
            self.logger.warning("Panel freshness check is already running.  "
                                "Use 'Stop Panel Freshness Check' to cancel it first.")
            return

        self._freshness_stop.clear()
        # Pick fresh random panels for every device at the start of each run
        self._freshness_sample_panels.clear()
        self._freshness_thread = threading.Thread(
            target=self._freshness_thread_loop, daemon=True
        )
        self._freshness_thread.start()
        self.logger.info("Panel freshness check started (runs for up to 15 minutes).")

    def stopFreshnessCheck(self):
        """Menu callback – stop the running freshness diagnostic early."""
        if self._freshness_thread is None or not self._freshness_thread.is_alive():
            self.logger.info("Panel freshness check is not running.")
            return
        self._freshness_stop.set()
        self.logger.info("Panel freshness check stop requested – will finish current cycle and exit.")

    # ── background thread entry point ────────────────────────────
    def _freshness_thread_loop(self):
        """Runs _compare_panel_freshness every 60 s for up to 15 min."""
        DURATION = 15 * 60   # 15 minutes
        INTERVAL = 60        # poll every 60 s
        start = time.monotonic()

        try:
            while not self._freshness_stop.is_set():
                elapsed = time.monotonic() - start
                if elapsed >= DURATION:
                    self.logger.info("Panel freshness check: 15-minute window reached – stopping automatically.")
                    break

                remaining_min = (DURATION - elapsed) / 60.0
                self.logger.info(f"Panel freshness check: {remaining_min:.1f} min remaining")

                for dev in indigo.devices.iter('self.EnphaseEnvoyDevice'):
                    if self._freshness_stop.is_set():
                        break
                    if not dev.enabled:
                        continue
                    if not dev.states.get('deviceIsOnline', False):
                        continue
                    if not dev.pluginProps.get('activatePanels', False):
                        continue
                    try:
                        self._compare_panel_freshness(dev)
                    except Exception:
                        self.logger.exception(f"Freshness check failed for {dev.name}")

                # Sleep in 1-s increments so we can respond to stop quickly
                for _ in range(INTERVAL):
                    if self._freshness_stop.is_set():
                        break
                    time.sleep(1)

        except Exception:
            self.logger.exception("Freshness check thread crashed")
        finally:
            self.logger.info("Panel freshness check finished.")

    # ── single-pass comparison (called by the thread) ────────────
    def _compare_panel_freshness(self, dev):
        """Call all 3 panel endpoints, pick 5 random panels, info-log which is newest.

        This is a **diagnostic-only** helper used by the on-demand
        freshness-check thread (started from the Plugin menu).

        The 5 sample panel serial numbers are chosen once per run and
        re-used on every subsequent call so the log output is comparable
        across cycles.
        """
        # ── 1. Fetch all three endpoints ──────────────────────────
        # legacy  → list of {serialNumber, lastReportWatts, lastReportDate, …}
        legacy_raw = self._getthePanels_legacy(dev)
        # device_data → parsed list of {sn, watts, last_reading, …}
        dd_raw = self.getDeviceData(dev)
        # devstatus → parsed list of {sn, last_reading, ac_power, …}  (installer only)
        ds_raw = None
        if self._is_installer_token(dev):
            ds_raw = self.getDevStatus(dev)

        # Build {sn → epoch} and {sn → watts} lookups for each source
        legacy_ts = {}
        legacy_w = {}
        if legacy_raw:
            for p in legacy_raw:
                sn = str(p.get('serialNumber', ''))
                legacy_ts[sn] = int(p.get('lastReportDate', 0))
                legacy_w[sn] = p.get('lastReportWatts', 0)

        dd_ts = {}
        dd_w = {}
        if dd_raw:
            for p in dd_raw:
                sn = str(p.get('sn', ''))
                dd_ts[sn] = int(p.get('last_reading', 0))
                dd_w[sn] = p.get('watts', 0)

        ds_ts = {}
        ds_w = {}
        if ds_raw:
            for p in ds_raw:
                sn = str(p.get('sn', ''))
                ds_ts[sn] = int(p.get('last_reading', 0))
                # ac_power from parseDevStatus is in milliwatts
                raw_mw = p.get('ac_power', 0)
                try:
                    ds_w[sn] = round(float(raw_mw) / 1000, 1)
                except (ValueError, TypeError):
                    ds_w[sn] = 0

        # ── 2. Build the union of all known serial numbers ────────
        all_sns = sorted(set(list(legacy_ts.keys()) + list(dd_ts.keys()) + list(ds_ts.keys())))
        if not all_sns:
            self.logger.info(f"[{dev.name}] Freshness check: no panels returned from any endpoint")
            return

        # ── 3. Pick 5 random sample panels (stable across the run) ──
        sample = self._freshness_sample_panels.get(dev.id)
        if not sample or not set(sample).issubset(set(all_sns)):
            k = min(5, len(all_sns))
            sample = random.sample(all_sns, k)
            self._freshness_sample_panels[dev.id] = sample
            self.logger.info(f"[{dev.name}] Freshness check: locked sample panels → {sample}")

        # ── 4. Log the comparison ─────────────────────────────────
        self.logger.info(f"[{dev.name}] ── Panel Freshness Check ({len(all_sns)} total inverters) ──")
        sources_available = []
        if legacy_raw:
            sources_available.append("legacy")
        if dd_raw:
            sources_available.append("device_data")
        if ds_raw:
            sources_available.append("devstatus")
        self.logger.info(f"[{dev.name}]   Sources responding: {', '.join(sources_available) if sources_available else 'NONE'}")

        winner_tally = {"legacy": 0, "device_data": 0, "devstatus": 0, "tie": 0}

        def _fmt(epoch):
            if epoch == 0:
                return "N/A"
            return datetime.datetime.fromtimestamp(epoch).strftime("%H:%M:%S")

        for sn in sample:
            ts_leg = legacy_ts.get(sn, 0)
            ts_dd  = dd_ts.get(sn, 0)
            ts_ds  = ds_ts.get(sn, 0)

            w_leg = legacy_w.get(sn, "N/A")
            w_dd  = dd_w.get(sn, "N/A")
            w_ds  = ds_w.get(sn, "N/A")

            best_ts = max(ts_leg, ts_dd, ts_ds)
            if best_ts == 0:
                winner = "none"
            elif [ts_leg, ts_dd, ts_ds].count(best_ts) > 1:
                winner = "tie"
                winner_tally["tie"] += 1
            elif best_ts == ts_ds:
                winner = "devstatus"
                winner_tally["devstatus"] += 1
            elif best_ts == ts_dd:
                winner = "device_data"
                winner_tally["device_data"] += 1
            else:
                winner = "legacy"
                winner_tally["legacy"] += 1

            self.logger.info(
                f"[{dev.name}]   SN {sn}: "
                f"legacy={_fmt(ts_leg)} {w_leg}W  "
                f"device_data={_fmt(ts_dd)} {w_dd}W  "
                f"devstatus={_fmt(ts_ds)} {w_ds}W  "
                f"→ {winner}"
            )

        self.logger.info(
            f"[{dev.name}]   Tally: legacy={winner_tally['legacy']}  "
            f"device_data={winner_tally['device_data']}  "
            f"devstatus={winner_tally['devstatus']}  "
            f"tie={winner_tally['tie']}"
        )
        self.logger.info(f"[{dev.name}] ── End Freshness Check ──")


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
            self.logger.debug(u"shutdown() method called.")

    def startup(self):
        if self.debugLevel >= 2:
            self.logger.debug(u"Starting Enphase Plugin. startup() method called.")

        # See if there is a plugin update and whether the user wants to be notified.

    def validatePrefsConfigUi(self, valuesDict):
        if self.debugLevel >= 2:
            self.logger.debug(u"validatePrefsConfigUi() method called.")

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
        generate_token = dev.pluginProps.get('generate_token', False)
        auth_token = dev.pluginProps.get('auth_token', "")
        use_token = dev.pluginProps.get('use_token', False)
        username = dev.pluginProps.get("enphase_user","")
        password = dev.pluginProps.get("enphase_password","")
        self.logger.debug(f"Use Manual token: {use_token} & Generate Token {generate_token}")


        if use_token==False and generate_token==False:
            self.logger.debug("Not using Tokens.")
            self.using_token = False
            self.https_flag=""
            return headers

        # always set https flag if using any token, indicates Firmware >7
        self.https_flag = "s"
        self.using_token = True

        if use_token and auth_token =="":
            self.logger.error("To use your own manual token you must enter it first.  Please do so asap.")
            return headers

        if use_token and auth_token !="":
            # Using manual token
            headers = {"Accept": "application/json", "Authorization": "Bearer "+str(auth_token)}
            self.logger.debug(f"Using Headers: {headers}")
            if self.log_manual_expiry:
                self._log_token_info(auth_token, dev, source="manual")
                try:
                    exp = self._get_enphase_token_expiry(auth_token)
                    dev.updateStateOnServer("token_expires", f"{datetime.datetime.fromtimestamp(exp).strftime('%c') if exp else 'unknown'}")
                except Exception:
                    self.logger.debug("Manual token found, but could not parse expiry.", exc_info=True)
                self.log_manual_expiry = False


        if self.serial_number_full.get(dev.id, "") == "":
            self.get_serial_number(dev)

        if generate_token:
            self.https_flag="s"
            # Only trust saved auth_token if it was actually generated (not a leftover manual token)
            token_source = dev.pluginProps.get("token_source", "")
            saved_is_generated = (token_source == "generated")
            # Startup: only when we haven't loaded token into memory yet
            if self.generated_token.get(dev.id, "") == "":
                saved = dev.pluginProps.get("auth_token", "") if saved_is_generated else ""
                if saved:
                    try:
                        self._log_token_info(saved, dev, source="saved/cached")
                        exp = self._get_enphase_token_expiry(saved)
                        dev.updateStateOnServer("token_expires",
                                                f"{datetime.datetime.fromtimestamp(exp).strftime('%c') if exp else 'unknown'}")
                    except Exception:
                        self.logger.debug("Saved token found, but could not parse expiry.", exc_info=True)
                else:
                    if not saved_is_generated and dev.pluginProps.get("auth_token", ""):
                        self.logger.info(
                            "Ignoring saved token — it was from manual entry, not generated. Will generate a fresh token.")
                    else:
                        self.logger.info(
                            "No saved Enphase token found on device; will attempt to generate/refresh when needed.")

            # Load token into runtime cache (after the one-time log)
            if saved_is_generated:
                self.generated_token[dev.id] = dev.pluginProps.get("auth_token", "") or self.generated_token.get(dev.id, "")

            if username == "":
                self.logger.error("To Generate a token you must enter username in device edit settings for enphase")
                return headers
            if password == "":
                self.logger.error("To Generate a token you must enter password in device edit settings for enphase")
                return headers
            if (not self.generated_token.get(dev.id, "")) or self._is_enphase_token_expired(self.generated_token[dev.id]):
                self.get_enphasetoken(username, password, self.serial_number_full.get(dev.id,""), dev)
                # (optional but safe) reload in case get_enphasetoken saved to pluginProps
                self.generated_token[dev.id] = dev.pluginProps.get("auth_token", "") or self.generated_token.get(dev.id,"")
            headers = {"Accept": "application/json",  "Authorization": "Bearer " + str(self.generated_token.get(dev.id, ""))}

        return headers

    def login(self, headers, dev):
        try:
            # If successful this will return a "sessionid" cookie that validates our access to the gateway.
            url = f"http{self.https_flag}://{dev.pluginProps['sourceXML']}/auth/check_jwt"  # Added lines TSH 7/19/23
            response = self._get(url, headers=headers)
            #response = self.session.get(url, headers=headers, verify=False, allow_redirects=True)  # Added lines TSH 7/19/23
            # Check the response is positive.
            return response.status_code
        except:
            self.logger.info("Error with getting SessionID via check_jwt.")
            if self.debug:
                self.logger.debug("Error with getting SessionID via check_jwt",exc_info=True)
            return ""

    def detect_model(self, dev):
        """Method to determine if the Envoy supports consumption values or
         only production"""

        headers =  self.create_headers(dev)
        self.endpoint_url = f"http{self.https_flag}://{dev.pluginProps['sourceXML']}/production.json"
        self.logger.debug("trying Endpoint:"+str(self.endpoint_url))
        self.endpoint_url = f"http{self.https_flag}://{dev.pluginProps['sourceXML']}/production.json"

        #response = self.session.get(  self.endpoint_url, timeout=25, verify=False, headers=headers,allow_redirects=True)
        response = self._get(self.endpoint_url, timeout=25, headers=headers)
        if response.status_code == 200 and self.hasProductionAndConsumption(response.json()):
            # Okay - this is Envoy S or Envoy-S Metered
            # Some have lots of blanks, need a new device type
            # CHange of plans - leave here for Legacy support, add check for EnvoyS types within this device type
            self.endpoint_type = "PC"
            self.logger.info("Success with EndPoint: " + str(self.endpoint_url))
            self.logger.info(f"Response\n:{response}")
            return True
        else:

            headers = self.create_headers( dev)
            self.endpoint_url = f"http{self.https_flag}://{dev.pluginProps['sourceXML']}/api/v1/production"
            self.logger.debug("trying Endpoint:" + str(self.endpoint_url))
            response = self._get( self.endpoint_url, headers=headers)
            if response.status_code == 200:
                self.endpoint_type = "P"       # Envoy-C, production only
                self.logger.info("Success with EndPoint: "+ str(self.endpoint_url))
                self.logger.info(f"Response\n:{response}")
                return True
            else:

                headers = self.create_headers( dev)
                self.endpoint_url = f"http{self.https_flag}://{dev.pluginProps['sourceXML']}/production"
                self.logger.debug("trying Endpoint:" + str(self.endpoint_url))
                response = self._get(self.endpoint_url, headers=headers)
                if response.status_code == 200:
                    self.endpoint_type = "P0"       # older Envoy-C
                    self.logger.debug("Success with EndPoint: " + str(self.endpoint_url))
                    return True

        self.endpoint_url = ""
        self.logger.info(
            "Could not connect or determine Envoy model. " +
            f"Check that the device is up at 'http{self.https_flag}://" + self.host + "'.")
        return False

    def call_api(self, dev):
        """Method to call the Envoy API"""
        # detection of endpoint if not already known
        try:
            if self.endpoint_type == "":
                self.detect_model(dev)
            response =  requests.get(self.endpoint_url, timeout=15,verify=False,  allow_redirects=True)
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
            self.logger.debug(u"getTheDataAll Models method called.")
        self.logger.debug("Checking Model & getting data of dev.id" + str(dev.name))

        if self.endpoint_type == "":
            if self.detect_model(dev):
                dev.updateStateOnServer('deviceIsOnline', value=True, uiValue="Online")
                dev.setErrorStateOnServer(None)
                self.WaitInterval = 0
            else:
                self.WaitInterval = 60
                if self.debugLevel >= 2:
                    self.logger.debug(u"Device is offline. No data to return. ")
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
            self.logger.debug("Attempting to locate serial number")
            try:
                #headers = self.create_headers( dev)
                #url = f"http{self.https_flag}://{dev.pluginProps['sourceXML']}/info.xml"

                url = f"http{self.https_flag}://{dev.pluginProps['sourceXML']}/info.xml"
                response = self._get(url, headers=None, verify=False)

                self.logger.debug(f"{response.text}")
                #response = requests.get( url, timeout=30, allow_redirects=True, verify=False)
                if len(response.text) > 0:
                    sn = response.text.split("<sn>")[1].split("</sn>")[0][-6:]
                    self.serial_number_last_six[dev.id] = sn
                    self.serial_number_full[dev.id] = response.text.split("<sn>")[1].split("</sn>")[0]
                    software = response.text.split("<software>")[1].split("</software>")[0] if "<software>" in response.text else ""
                    imeter = response.text.split("<imeter>")[1].split("</imeter>")[0] if "<imeter>" in response.text else ""

                    self.logger.debug(f"[{dev.name}] Found 6 digit Serial Number:"+str(self.serial_number_last_six[dev.id]))
                    self.logger.info(f"[{dev.name}] Found Full Enphase Envoy Serial Number:" + str(self.serial_number_full[dev.id]))
                    dev.updateStateOnServer("serial_number", f"{self.serial_number_full[dev.id]}")
                    if software:
                        self.logger.info(f"[{dev.name}] Envoy firmware: {software}")
                        dev.updateStateOnServer('firmware_version', value=f"{software}")
                    if imeter:
                        self.logger.debug(f"[{dev.name}] iMeter enabled: {imeter}")
                    return True
            except requests.exceptions.ConnectionError:
                self.logger.info(f"Error connecting to info.xml to find Serial Number")
                return False
        else:
            self.logger.debug("Using Serial Number entered manually in device settings.")
            self.serial_number_last_six[dev.id] = serial_num[-6:]
            self.serial_number_full[dev.id] = serial_num
            self.logger.debug("Found 6 digit Serial Number:" + str(self.serial_number_last_six[dev.id]))
            self.logger.info(f"[{dev.name}] Found Full Enphase Envoy Serial Number:" + str(self.serial_number_full[dev.id]))
            return serial_num[-6:]

    def gettheDataChoice(self,dev):
        envoyType= dev.states["typeEnvoy"]
        unmetered =  dev.pluginProps.get('unmetered', False)
        if envoyType == "Metered" or unmetered:
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
            self.logger.debug(u"getTheData PRODUCTION METHOD method called.")

        try:
            headers = self.create_headers( dev)
            url = f"http{self.https_flag}://{dev.pluginProps['sourceXML']}/production.json"

            host = urlsplit(url).netloc  # same host key used in _get
            session = self.session_cache[host]  # auto-creates if first touch
            self.logger.debug(f"\n Using URL {url}\n Cookies: {session.cookies.get_dict()}\n Headers {headers}")
            r = self._get( url, headers=headers)
            #r = self.session.get(url, timeout=35, headers=headers, verify=False, allow_redirects=True)
            if r.status_code != 200:
                raise Exception(f"HTTP {r.status_code} from {url}")
            result = r.json()
            self.logger.debug(f"Result:{result}")

            dev.updateStateOnServer('deviceIsOnline', value=True, uiValue="Online")
            dev.setErrorStateOnServer(None)
            self.WaitInterval = 0
            return result

        except Exception as error:
            self.logger.debug("Exception:", exc_info=True)
            indigo.server.log(u"Error connecting to Device:" + str(dev.name) +" Error is:"+str(error))
            self.WaitInterval = 60
            self.logger.debug(u"Device is offline. No data to return. ", exc_info=False)
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
            self.logger.debug(u"legacygetTheData PRODUCTION METHOD method called.")

        try:

            headers = self.create_headers(dev)
            url = f"http{self.https_flag}://{dev.pluginProps['sourceXML']}/api/v1/production"
            r = self._get( url, headers=headers)
            #r = self.session.get(url,timeout=15 ,headers=headers,verify=False,  allow_redirects=True)
            if r.status_code != 200:
                raise Exception(f"HTTP {r.status_code} from {url}")
            result = r.json()
            if self.debugLevel >= 2:
                self.logger.debug(u"Result:" + str(result))
            dev.updateStateOnServer('deviceIsOnline', value=True, uiValue="Online")
            dev.setErrorStateOnServer(None)
            self.WaitInterval = 0

            return result

        except Exception as error:

            indigo.server.log(u"Error connecting to Device:" + str(dev.name) +"Error is:"+str(error))
            self.WaitInterval = 60
            if self.debugLevel >= 2:
                self.logger.debug(u"Device is offline. No data to return. ")
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
            self.logger.debug(u"getAPIDataConsumption METHOD method called.")

        try:

            headers = self.create_headers( dev)
            url = f"http{self.https_flag}://{dev.pluginProps['sourceXML']}/api/v1/consumption"
            r = self._get( url, headers=headers)
            #r = self.session.get(url,timeout=15, verify=False,  headers=headers, allow_redirects=True)
            if r.status_code != 200:
                raise Exception(f"HTTP {r.status_code} from {url}")
            result = r.json()
            if self.debugLevel >= 2:
                self.logger.debug(u"Result:" + str(result))
            self.WaitInterval = 0
            return result

        except Exception as error:
            self.logger.debug("Exception in LegacyConsumption Data. Perhaps doesn't exist.")
            result = None
            return result

    def getPdmEnergy(self, dev):
        """
        Fetch production energy data from /ivp/pdm/energy.
        This installer-level endpoint returns more accurate production
        values directly from the power/device manager.
        Returns the JSON dict, or None on failure.
        """
        try:
            headers = self.create_headers(dev)
            if not headers:
                return None
            url = f"http{self.https_flag}://{dev.pluginProps['sourceXML']}/ivp/pdm/energy"
            r = self._get(url, timeout=35, headers=headers)
            if r.status_code == 200:
                result = r.json()
                if self.debugLevel >= 2:
                    self.logger.debug(f"PDM Energy Result: {result}")
                return result
            else:
                if self.debugLevel >= 2:
                    self.logger.debug(f"PDM Energy returned status {r.status_code}")
                return None
        except Exception as error:
            if self.debugLevel >= 2:
                self.logger.debug(f"Exception fetching PDM energy: {error}", exc_info=True)
            return None

    def _applyPdmEnergy(self, dev):
        """
        If an installer-level token is available, fetch /ivp/pdm/energy
        and override the production values with the more accurate PDM data.
        Based on the vincentwolsink HA integration's path_by_token pattern
        that prefers pdm_energy.production.pcu for installer tokens.
        """
        if not self._is_installer_token(dev):
            return
        pdm = self.getPdmEnergy(dev)
        if pdm is None:
            return
        try:
            pcu = pdm.get("production", {}).get("pcu", {})
            if not pcu:
                return
            updates = []
            if "wattsNow" in pcu:
                updates.append({'key': 'productionWattsNow', 'value': int(pcu['wattsNow'])})
            if "wattHoursToday" in pcu:
                updates.append({'key': 'productionWattsToday', 'value': int(pcu['wattHoursToday'])})
            if "wattHoursLifetime" in pcu:
                updates.append({'key': 'productionwhLifetime', 'value': int(pcu['wattHoursLifetime'])})
            if "wattHoursSevenDays" in pcu:
                updates.append({'key': 'production7days', 'value': int(pcu['wattHoursSevenDays'])})
            if updates:
                dev.updateStatesOnServer(updates)
                if self.debugLevel >= 2:
                    self.logger.debug(f"Production values overridden from PDM energy: {updates}")
        except Exception as error:
            if self.debugLevel >= 2:
                self.logger.debug(f"Error applying PDM energy data: {error}", exc_info=True)


    def checkThePanels_New(self,dev, thePanels=None):
        if self.debugLevel >= 2:
            self.logger.debug(u'check thepanels called')
        if dev.pluginProps['activatePanels']:
            if thePanels == None:
                self.thePanels = self.getthePanels(dev)
            else:
                self.thePanels = thePanels

            try:
                if self.thePanels is not None:
                    x = 1
                    update_time = t.strftime("%m/%d/%Y at %H:%M")
                    dev.updateStateOnServer('panelLastUpdated', value=update_time  )
                    dev.updateStateOnServer('panelLastUpdatedUTC', value=float(t.time())  )
                    now_epoch = int(t.time())
                    for paneldev in indigo.devices.iter('self.EnphasePanelDevice'):
                        for panel in self.thePanels:
                            if float(paneldev.states['serialNo']) == float(panel['serialNumber']):
                                report_ts = int(panel.get('lastReportDate', 0))
                                is_gone = bool(panel.get('gone', False))

                                # Determine if panel data is stale
                                is_stale = False
                                if is_gone:
                                    is_stale = True
                                elif report_ts > 0 and (now_epoch - report_ts) > PANEL_STALE_THRESHOLD_SECS:
                                    is_stale = True

                                if is_stale:
                                    # Panel is not communicating or data is stale
                                    paneldev.updateStateOnServer('watts', value=0, uiValue='0')
                                    paneldev.updateStateOnServer('communicating', value=False)
                                    paneldev.updateStateOnServer('deviceIsOnline', value=False, uiValue="Offline")
                                    paneldev.updateStateOnServer('deviceLastUpdated', value=update_time)
                                    paneldev.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)
                                    # Preserve the last known communication time
                                    if report_ts > 0:
                                        paneldev.updateStateOnServer('lastCommunication', value=str(datetime.datetime.fromtimestamp(report_ts).strftime('%c')))
                                    if self.debugLevel >= 1:
                                        age_mins = round((now_epoch - report_ts) / 60, 1) if report_ts > 0 else "N/A"
                                        self.logger.debug(
                                            f"Panel {panel['serialNumber']} marked stale/offline "
                                            f"(gone={is_gone}, last_report_age={age_mins} min)")
                                    continue
                                else:
                                    paneldev.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)

                                # Panel is online and current
                                paneldev.updateStateOnServer('watts',value=int(panel['lastReportWatts']),uiValue=str(panel['lastReportWatts']))
                                # Only update lastCommunication when the timestamp is valid (> 0).
                                # Devstatus returns last_reading=0 for offline/gone inverters;
                                # converting 0 to a date produces "Jan 1 1970" which is misleading.
                                # Keeping the previous value preserves the real last-seen time.
                                if report_ts > 0:
                                    paneldev.updateStateOnServer('lastCommunication', value=str(datetime.datetime.fromtimestamp(report_ts).strftime('%c')))
                                paneldev.updateStateOnServer('maxWatts', value=int(panel['maxReportWatts']))
                                paneldev.updateStateOnServer('deviceLastUpdated', value=update_time)
                                paneldev.updateStateOnServer('deviceIsOnline', value=True, uiValue="Online")
                                paneldev.setErrorStateOnServer(None)


                                # Extra extended fields (present when data from device_data or devstatus)
                                if panel.get('_source') in ('device_data', 'devstatus'):
                                    if panel.get('ac_power_watts') is not None:
                                        ac_w = panel['ac_power_watts']
                                        paneldev.updateStateOnServer('acPower', value=ac_w, uiValue=f"{ac_w} W")
                                    if panel.get('ac_voltage') is not None:
                                        ac_v = round(panel['ac_voltage'], 2)
                                        paneldev.updateStateOnServer('acVoltage', value=ac_v, uiValue=f"{ac_v} V")
                                    if panel.get('dc_voltage') is not None:
                                        dc_v = round(panel['dc_voltage'], 2)
                                        paneldev.updateStateOnServer('dcVoltage', value=dc_v, uiValue=f"{dc_v} V")
                                    if panel.get('dc_current') is not None:
                                        dc_a = round(panel['dc_current'], 3)
                                        paneldev.updateStateOnServer('dcCurrent', value=dc_a, uiValue=f"{dc_a} A")
                                    if panel.get('temperature') is not None:
                                        temp = panel['temperature']
                                        paneldev.updateStateOnServer('temperature', value=temp, uiValue=f"{temp} °C")
                                    if panel.get('gone') is not None:
                                        # gone=True means inverter is NOT communicating
                                        paneldev.updateStateOnServer('communicating', value=not panel['gone'])
                                    # device_data-only extended fields
                                    if panel.get('ac_current') is not None:
                                        ac_a = round(panel['ac_current'], 3)
                                        paneldev.updateStateOnServer('acCurrent', value=ac_a, uiValue=f"{ac_a} A")
                                    if panel.get('ac_frequency') is not None:
                                        ac_hz = round(panel['ac_frequency'], 3)
                                        paneldev.updateStateOnServer('acFrequency', value=ac_hz, uiValue=f"{ac_hz} Hz")
                                    if panel.get('watt_hours_today') is not None:
                                        paneldev.updateStateOnServer('wattHoursToday', value=int(panel['watt_hours_today']))
                                    if panel.get('watt_hours_week') is not None:
                                        paneldev.updateStateOnServer('wattHoursWeek', value=int(panel['watt_hours_week']))
                                    if panel.get('lifetime_power') is not None:
                                        paneldev.updateStateOnServer('lifetimeEnergy', value=int(panel['lifetime_power']))


            except Exception as error:
                self.errorLog('error within checkthePanels:'+str(error))
                if self.debugLevel >= 2:
                    self.logger.debug(u"Device is offline. No data to return. ", exc_info=True)
                paneldev.updateStateOnServer('deviceIsOnline', value=False, uiValue="Offline")
                paneldev.setErrorStateOnServer(u'Offline')
                result = None

                return result
        return


    def checkPanelInventory(self,dev):
        if self.debugLevel >= 2:
            self.logger.debug(u"checkPanelInventory Enphase Panels method called.")

        if dev.pluginProps['activatePanels'] and dev.states['deviceIsOnline']:
            self.inventoryDict = self.getInventoryData(dev)

            try:
                if self.inventoryDict is not None:
                    for dev in indigo.devices.iter('self.EnphasePanelDevice'):
                        for devices in self.inventoryDict[0]['devices']:
                            #if self.debugLevel >=2:
                               # self.logger.debug(u'checking serial numbers')
                               # self.errorLog(u'device serial:'+str(int(dev.states['serialNo'])))
                               # self.errorLog(u'panel serial no:'+str(devices['serial_num']))
                            #self.errorLog(u'Dev.states Producing type is' + str(type(dev.states['producing'])))
                            #self.errorLog(u'Devices Producing type is' + str(type(devices['producing'])))
                            if float(dev.states['serialNo']) == float(devices['serial_num']):
                                if dev.states['producing']==True and devices['producing']==False:
                                    if self.debugLevel >= 1:
                                        self.logger.debug(u'Producing: States true, devices(producing) False: devices[producing] equals:'+str(devices['producing']))
                                    #  change only once
                                    dev.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)
                                    dev.updateStateOnServer('watts', value=0, uiValue='--')
                                if dev.states['producing'] == False and devices['producing'] == True:
                                    if self.debugLevel >= 1:
                                        self.logger.debug(u'States Producing False, and devices now shows True: device(producing):' + str(devices['producing']))
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
                    self.logger.debug(u"Device is offline. No data to return. ")
                dev.updateStateOnServer('deviceIsOnline', value=False, uiValue="Offline")
                dev.setErrorStateOnServer(u'Offline')
                result = None
                return result

        return


    def getInventoryData(self, dev):

        if self.debugLevel >= 2:
            self.logger.debug(u"getInventoryData Enphase Panels method called.")
        try:
            headers = self.create_headers(dev)
            url = f"http{self.https_flag}://{dev.pluginProps['sourceXML']}/inventory.json"
            r = self._get(url, timeout=35,  headers=headers)
            #r = self.session.get(url, timeout=35, verify=False, headers=headers,allow_redirects=True)
            if r.status_code != 200:
                raise Exception(f"HTTP {r.status_code} from {url}")
            result = r.json()
            if self.debug:
                self.logger.debug(u"Inventory Result:" + str(result))
            return result

        except Exception as error:

            indigo.server.log(u"Error connecting to Device:" + dev.name)
            if self.debugLevel >= 2:
                self.logger.debug(u"Device is offline. No data to return. ")
            # dev.updateStateOnServer('deviceTimestamp', value=t.time())
            result = None
            self.WaitInterval = 60
            return result

    def getthePanels(self, dev):
        """Fetch per-inverter **real-time watts** and merge cached extended data.

        Called every ~60 s by the ``panel_health`` timer.

        * Always fetches ``/api/v1/production/inverters`` for near-
          real-time watt/timestamp readings (< 1 min delay).
        * Merges in **cached** extended data (temperature, voltage,
          current, wattHours, lifetime energy …) that was last
          refreshed by ``_refreshPanelExtendedData()`` on the slower
          ``panel_extended`` timer (~15 min).
        * Never calls ``/ivp/pdm/device_data`` or ``/ivp/peb/devstatus``
          itself — those are fetched only on the 15-min cadence.

        Returns a list of dicts in the unified format:

            serialNumber, lastReportWatts, lastReportDate, maxReportWatts

        with extended keys when cached enrichment data is available.
        """
        if self.debugLevel >= 2:
            self.logger.debug(u"getthePanels Enphase Envoy method called.")

        if not dev.states['deviceIsOnline']:
            return None

        # ── 1. Real-time watts from /api/v1/production/inverters ──
        realtime = self._getthePanels_legacy(dev)
        source = "inverters"

        if realtime:
            # Build a serial-number → dict lookup for the real-time data
            rt_by_sn = {str(p['serialNumber']): p for p in realtime}

            # ── 2. Merge cached extended data (if any) ───────────
            cached = self._cached_panel_extended.get(dev.id)
            if cached:
                self._enrich_panels(rt_by_sn, cached, cached.get('_ext_source', 'cached'))
                source = f"inverters+{cached.get('_ext_source', 'cached')}"

            # Update the data-source state on the Envoy device
            try:
                dev.updateStateOnServer('panelDataSource', value=source)
            except Exception:
                pass  # state may not exist on older device configs

            if self.debugLevel >= 2:
                self.logger.debug(
                    f"getthePanels: returning {len(realtime)} inverters "
                    f"(source={source})"
                )
            return realtime

        # ── Fallback: if the legacy endpoint failed, use cached extended ──
        # ── data alone (it at least has watts, albeit delayed).           ──
        self.logger.debug("getthePanels: no data from /api/v1/production/inverters, using cached extended data if available")
        cached = self._cached_panel_extended.get(dev.id)
        if cached:
            # Return the cached unified dicts as a list
            panels = [v for k, v in cached.items() if k != '_ext_source' and isinstance(v, dict)]
            if panels:
                source = cached.get('_ext_source', 'cached')
                try:
                    dev.updateStateOnServer('panelDataSource', value=source)
                except Exception:
                    pass
                return panels

        return None

    def _refreshPanelExtendedData(self, dev):
        """Fetch extended panel data and cache it for the fast 60 s cycle.

        Called every ~15 min by the ``panel_extended`` timer.

        Tries ``/ivp/pdm/device_data`` first (available with any token,
        richest data).  Falls back to ``/ivp/peb/devstatus`` (installer
        token only).

        The result is stored in ``self._cached_panel_extended[dev.id]``
        as a ``{serialNumber: unified_dict, …, '_ext_source': …}`` dict
        so that ``getthePanels()`` can merge it into fresh real-time
        watts without making additional HTTP calls.
        """
        if not dev.states.get('deviceIsOnline', False):
            return
        if not dev.pluginProps.get('activatePanels', False):
            return

        ext_source = None
        unified_ext = None

        # Try device_data first (any token, richest extended data)
        device_data = self.getDeviceData(dev)
        if device_data:
            unified_ext = self._devicedata_to_unified(device_data)
            if unified_ext:
                ext_source = "device_data"

        # If device_data was not available, try devstatus (installer token)
        if unified_ext is None and self._is_installer_token(dev):
            devstatus = self.getDevStatus(dev)
            if devstatus:
                unified_ext = self._devstatus_to_unified(devstatus)
                if unified_ext:
                    ext_source = "devstatus"

        if unified_ext:
            # Store as a {serialNumber → dict} lookup, plus a meta key
            cache = {str(p['serialNumber']): p for p in unified_ext}
            cache['_ext_source'] = ext_source
            self._cached_panel_extended[dev.id] = cache
            self.logger.debug(
                f"Cached extended panel data for {dev.name}: "
                f"{len(unified_ext)} inverters from {ext_source}"
            )
        else:
            if self.debugLevel >= 2:
                self.logger.debug(
                    f"No extended panel data available for {dev.name}"
                )

    def _enrich_panels(self, rt_by_sn, cached_ext, ext_source):
        """Merge cached extended fields into real-time panel dicts.

        *rt_by_sn* is a {serialNumber: dict} lookup of real-time data.
        *cached_ext* is the cache dict {serialNumber: unified_dict, '_ext_source': …}.
        *ext_source* is 'device_data' or 'devstatus' — stored as ``_source``.

        Core real-time keys (serialNumber, lastReportWatts, maxReportWatts)
        are never overwritten by extended data.

        ``lastReportDate`` is special-cased: the **most recent** timestamp
        from either source is kept so that stale-panel detection always
        uses the freshest available reading.
        """
        CORE_KEYS = {'serialNumber', 'lastReportWatts', 'maxReportWatts'}
        for sn, ext in cached_ext.items():
            if sn.startswith('_') or not isinstance(ext, dict):
                continue  # skip meta keys like '_ext_source'
            if sn in rt_by_sn:
                panel = rt_by_sn[sn]
                for key, value in ext.items():
                    if key in CORE_KEYS:
                        continue
                    if key == 'lastReportDate':
                        # Keep the most recent timestamp from either source
                        try:
                            rt_ts = int(panel.get('lastReportDate', 0))
                        except (ValueError, TypeError):
                            rt_ts = 0
                        try:
                            ext_ts = int(value) if value else 0
                        except (ValueError, TypeError):
                            ext_ts = 0
                        if ext_ts > rt_ts:
                            if self.debugLevel >= 2:
                                self.logger.debug(
                                    f"_enrich_panels: {sn} using newer lastReportDate "
                                    f"from {ext_source} ({ext_ts}) over legacy ({rt_ts})"
                                )
                            panel['lastReportDate'] = ext_ts
                        continue
                    panel[key] = value
                panel['_source'] = ext_source


    def _devicedata_to_unified(self, devicedata_list):
        """Convert parseDeviceData() output into the unified panel format.

        Adds the standard keys (serialNumber, lastReportWatts,
        lastReportDate, maxReportWatts) expected by callers,
        plus extended keys for the richer device_data fields.
        """
        result = []
        for dd in devicedata_list:
            sn = dd.get("sn")
            if sn is None:
                continue
            panel = {
                # standard keys expected everywhere
                "serialNumber": sn,
                "lastReportWatts": dd.get("watts", 0),
                "lastReportDate": dd.get("last_reading", 0),
                "maxReportWatts": dd.get("watts_max", 0),
                # extended device_data fields
                "ac_power_watts": dd.get("watts", 0),
                "ac_voltage": round(dd["ac_voltage"], 2) if dd.get("ac_voltage") is not None else None,
                "ac_current": round(dd["ac_current"], 3) if dd.get("ac_current") is not None else None,
                "ac_frequency": round(dd["ac_frequency"], 3) if dd.get("ac_frequency") is not None else None,
                "dc_voltage": round(dd["dc_voltage"], 2) if dd.get("dc_voltage") is not None else None,
                "dc_current": round(dd["dc_current"], 3) if dd.get("dc_current") is not None else None,
                "temperature": dd.get("temperature"),
                "watt_hours_today": dd.get("watt_hours_today"),
                "watt_hours_week": dd.get("watt_hours_week"),
                "lifetime_power": dd.get("lifetime_power"),
                "gone": dd.get("gone"),
                "_source": "device_data",
            }
            result.append(panel)
        return result if result else None


    def _devstatus_to_unified(self, devstatus_list):
        """Convert parseDevStatus() output into the unified panel format.

        Adds the standard keys (serialNumber, lastReportWatts,
        lastReportDate, maxReportWatts) expected by callers,
        while keeping the original devstatus keys as extras.
        All power/voltage/current values are pre-converted to
        final display units so consumers don't need to re-convert.
        """
        result = []
        for ds in devstatus_list:
            sn = ds.get("sn")
            if sn is None:
                continue
            # ac_power from parseDevStatus is in milliwatts (field acPowerINmW
            # is not divided by 1000 there).  Convert to watts.
            ac_power_mw = ds.get("ac_power", 0)
            try:
                watts = round(float(ac_power_mw) / 1000, 1)
            except (ValueError, TypeError):
                watts = 0

            last_reading = ds.get("last_reading", 0)
            panel = {
                # standard keys expected everywhere
                "serialNumber": sn,
                "lastReportWatts": watts,
                "lastReportDate": last_reading,
                "maxReportWatts": 0,  # devstatus doesn't carry a max field
                # extra devstatus fields — pre-converted to final units
                "ac_power_watts": watts,  # W  (same as lastReportWatts)
                "ac_voltage": round(ds.get("ac_voltage"), 2) if ds.get("ac_voltage") is not None else None,
                "dc_voltage": round(ds.get("dc_voltage"), 2) if ds.get("dc_voltage") is not None else None,
                "dc_current": round(ds.get("dc_current"), 3) if ds.get("dc_current") is not None else None,
                "temperature": ds.get("temperature"),
                # 'gone' is True when the inverter is NOT communicating
                # (parseDevStatus inverts the raw 'communicating' bool)
                "gone": ds.get("gone"),
                "_source": "devstatus",
            }
            result.append(panel)
        return result if result else None

        # ---------------------------------------------------------

    def _getthePanels_legacy(self, dev):
        """Fetch panel data from the legacy /api/v1/production/inverters endpoint."""
        if self.serial_number_last_six.get(dev.id, "") == "":
            if self.get_serial_number(dev):
                self.logger.debug("Found the correct Serial Number.  Continuing.")
            else:
                self.logger.debug("Error getting Serial Number.  Cannot update panels unfortunately")
                return None
        try:
            headers = self.create_headers(dev)
            url = f"http{self.https_flag}://{dev.pluginProps['sourceXML']}/api/v1/production/inverters"
            if self.debugLevel >= 2:
                self.logger.debug(u"getthePanels (legacy): Password:" + str(self.serial_number_last_six))
            if self.https_flag == "s":
                r = self._get(url, timeout=35, headers=headers)
            else:
                auth = HTTPDigestAuth('envoy', self.serial_number_last_six)
                r = self._get(url, timeout=34, headers=headers, auth=auth)

            if r.status_code != 200:
                raise Exception(f"HTTP {r.status_code} from {url}")
            result = r.json()
            if self.debugLevel >= 2:
                self.logger.debug(f"Inverter Result (legacy):{result}")
            if "status" in result:
                if result["status"] == 401:
                    self.logger.info(f"Error getting Panel Data: Error : {result}")
                    return None
            return result

        except requests.exceptions.ReadTimeout as e:
            self.logger.debug("ReadTimeout with get Panel Devices:" + str(e))
            return None
        except requests.exceptions.Timeout as e:
            self.logger.debug("Timeout with get Panel Devices:" + str(e))
            return None
        except requests.exceptions.ConnectionError as e:
            self.logger.debug("ConnectionError with get Panel Devices:" + str(e))
            return None
        except requests.exceptions.ConnectTimeout as e:
            self.logger.debug("ConnectTimeout with get Panel Devices:" + str(e))
            return None
        except Exception as error:
            indigo.server.log(u"Error connecting to Device:" + dev.name)
            if self.debugLevel >= 2:
                self.logger.debug(u"Device is offline. No data to return. ", exc_info=True)
            dev.updateStateOnServer('deviceIsOnline', value=False, uiValue="Offline")
            for paneldevice in indigo.devices.iter('self.EnphasePanelDevice'):
                paneldevice.updateStateOnServer('deviceIsOnline', value=False, uiValue="Offline")
                paneldevice.updateStateOnServer('watts', value=0)
                paneldevice.setErrorStateOnServer(u'Offline')
            self.WaitInterval = 60
            return None

    def getDeviceData(self, dev):
        """
        Fetch per-inverter data from /ivp/pdm/device_data.
        This endpoint is available with any token (not installer-only)
        and returns the richest per-inverter data: watts, watts_max,
        wattHours today/yesterday/week, AC/DC voltage/current,
        temperature, lifetime energy, RSSI, and more.
        Returns the parsed list of device dicts, or None on failure.
        """
        try:
            headers = self.create_headers(dev)
            if not headers:
                return None
            url = f"http{self.https_flag}://{dev.pluginProps['sourceXML']}/ivp/pdm/device_data"
            r = self._get(url, timeout=35, headers=headers)
            if r.status_code == 200:
                raw = r.json()
                if self.debugLevel >= 2:
                    self.logger.debug(f"DeviceData raw result: {raw}")
                return self.parseDeviceData(raw)
            else:
                if self.debugLevel >= 2:
                    self.logger.debug(f"DeviceData returned status {r.status_code}")
                return None
        except Exception as error:
            if self.debugLevel >= 2:
                self.logger.debug(f"Exception fetching device_data: {error}", exc_info=True)
            return None

    def parseDeviceData(self, data):
        """
        Parse the /ivp/pdm/device_data response into a list of device dicts.
        Based on the vincentwolsink HA integration's parse_devicedata function.

        The response is a dict keyed by device EID, each value containing:
          devName, sn, active, modGone, channels[0].watts.now/max,
          channels[0].wattHours.today/yesterday/week,
          channels[0].lastReading.{acVoltageINmV, acFrequencyINmHz, ...}
          channels[0].lifetime.joulesProduced

        Returns a list of dicts with keys:
          sn, watts, watts_max, watt_hours_today, watt_hours_yesterday,
          watt_hours_week, ac_voltage, ac_frequency, ac_current,
          dc_voltage, dc_current, temperature, lifetime_power,
          gone, last_reading
        """
        result = []
        for device in data.values():
            if not isinstance(device, dict) or not device.get("active", False):
                continue
            if device.get("devName") != "pcu":
                continue

            dd = {}
            dd["sn"] = device.get("sn")
            dd["gone"] = device.get("modGone", False)

            channels = device.get("channels")
            if not channels or not isinstance(channels, list):
                result.append(dd)
                continue

            ch = channels[0]

            # watts.now and watts.max
            watts_info = ch.get("watts", {})
            dd["watts"] = watts_info.get("now", 0)
            dd["watts_max"] = watts_info.get("max", 0)

            # wattHours
            wh = ch.get("wattHours", {})
            dd["watt_hours_today"] = wh.get("today", 0)
            dd["watt_hours_yesterday"] = wh.get("yesterday", 0)
            dd["watt_hours_week"] = wh.get("week", 0)

            # lastReading - with mV/mA/mHz conversion
            lr = ch.get("lastReading", {})
            dd["last_reading"] = lr.get("endDate", 0)

            ac_v = lr.get("acVoltageINmV")
            dd["ac_voltage"] = int(ac_v) / 1000 if ac_v is not None else None

            ac_f = lr.get("acFrequencyINmHz")
            dd["ac_frequency"] = int(ac_f) / 1000 if ac_f is not None else None

            ac_i = lr.get("acCurrentInmA")
            dd["ac_current"] = int(ac_i) / 1000 if ac_i is not None else None

            dc_v = lr.get("dcVoltageINmV")
            dd["dc_voltage"] = int(dc_v) / 1000 if dc_v is not None else None

            dc_i = lr.get("dcCurrentINmA")
            dd["dc_current"] = int(dc_i) / 1000 if dc_i is not None else None

            dd["temperature"] = lr.get("channelTemp")

            # lifetime energy: joules -> Wh
            lifetime = ch.get("lifetime", {})
            joules = lifetime.get("joulesProduced")
            dd["lifetime_power"] = round(int(joules) * 0.000277778) if joules is not None else None

            result.append(dd)
            if self.debugLevel >= 2:
                self.logger.debug(f"Parsed device_data inverter: {dd}")

        return result if result else None

    def getDevStatus(self, dev):
        """
        Fetch inverter device status from /ivp/peb/devstatus.
        This endpoint requires an installer-level JWT token and returns
        detailed per-inverter data (temperature, DC/AC voltage/current, power).
        Returns the parsed list of device dicts, or None on failure.
        """
        try:
            headers = self.create_headers(dev)
            url = f"http{self.https_flag}://{dev.pluginProps['sourceXML']}/ivp/peb/devstatus"
            r = self._get(url, timeout=35, headers=headers)
            if r.status_code == 200:
                raw = r.json()
                if self.debugLevel >= 2:
                    self.logger.debug(f"DevStatus raw result: {raw}")
                return self.parseDevStatus(raw)
            else:
                if self.debugLevel >= 2:
                    self.logger.debug(f"DevStatus returned status {r.status_code}")
                return None
        except Exception as error:
            if self.debugLevel >= 2:
                self.logger.debug(f"Exception fetching devstatus: {error}", exc_info=True)
            return None

    def parseDevStatus(self, data):
        """
        Parse the /ivp/peb/devstatus response into a list of device dicts.
        Based on the vincentwolsink HA integration's parse_devstatus function.

        The response has a 'pcu' key containing:
          - 'fields': list of field names
          - 'values': list of value arrays (one per inverter)

        Returns a list of dicts with keys:
          sn, type, last_reading, temperature, dc_voltage, dc_current,
          ac_voltage, ac_power, gone (True if not communicating)
        """
        pcu_field_map = {
            "sn": "serialNumber",
            "type": "devType",
            "last_reading": "reportDate",
            "temperature": "temperature",
            "dc_voltage": "dcVoltageINmV",
            "dc_current": "dcCurrentINmA",
            "ac_voltage": "acVoltageINmV",
            "ac_power": "acPowerINmW",
            "gone": "communicating",
        }
        device_type_map = {1: "pcu", 12: "nsrb"}

        result = []
        for itemtype, content in data.items():
            if itemtype != "pcu":
                continue
            dataset = pcu_field_map

            fields = content.get("fields", [])
            values = content.get("values", [])

            # Build index map: our_key -> position in the values array
            field_index = {}
            for key, field_name in dataset.items():
                if field_name in fields:
                    field_index[key] = fields.index(field_name)

            for valueset in values:
                device_data = {}
                for key, idx in field_index.items():
                    try:
                        value = valueset[idx]
                    except (IndexError, TypeError):
                        continue
                    try:
                        if dataset[key].endswith(("mA", "mV", "mHz")):
                            device_data[key] = int(value) / 1000
                        elif key == "type":
                            device_data[key] = device_type_map.get(value, value)
                        elif key == "gone":
                            # Raw field is 'communicating' (True=talking).
                            # Invert so gone=True means NOT communicating.
                            device_data[key] = not value
                        else:
                            device_data[key] = value
                    except (ValueError, TypeError):
                        device_data[key] = value
                result.append(device_data)
                if self.debugLevel >= 2:
                    self.logger.debug(f"Parsed devstatus inverter: {device_data}")

        return result if result else None

    def _is_installer_token(self, dev):
        """Check whether the current token for this device is installer-level."""
        token = ""
        if dev.pluginProps.get('use_token', False):
            token = dev.pluginProps.get('auth_token', "")
        elif dev.pluginProps.get('generate_token', False):
            token = self.generated_token.get(dev.id, "")
        if token:
            return self._get_token_type(token) == "installer"
        return False

    def getMetersReadings(self, dev):
        """
        Fetch per-phase meter data from /ivp/meters/readings.
        Returns the JSON array of meter objects (each with 'channels' for per-phase data),
        or None on failure.
        """
        try:
            headers = self.create_headers(dev)
            url = f"http{self.https_flag}://{dev.pluginProps['sourceXML']}/ivp/meters/readings"
            r = self._get(url, headers=headers)
            if r.status_code == 200:
                result = r.json()
                if self.debugLevel >= 2:
                    self.logger.debug(f"Meters Readings Result: {result}")
                return result
            else:
                if self.debugLevel >= 2:
                    self.logger.debug(f"Meters Readings returned status {r.status_code}")
                return None
        except Exception as error:
            if self.debugLevel >= 2:
                self.logger.debug(f"Exception fetching meters readings: {error}")
            return None

    def parseMetersReadings(self, dev, metersData):
        """
        Parse the /ivp/meters/readings response and update per-phase device states.
        The response is a list of meter objects. Each meter may be production or
        consumption type (identified by measurementType or eid). Each meter has
        a 'channels' array with per-phase (L1, L2, L3) data.
        Meter-level fields: voltage, current, activePower, apparentPower,
                           reactivePower, pwrFactor, freq
        Channel-level fields (per-phase): same fields as meter level
        """
        if metersData is None:
            return
        try:
            # Identify production and consumption meters
            # The /ivp/meters endpoint returns meter config with measurementType
            # but /ivp/meters/readings uses eid to match. We'll try to identify
            # by checking for known patterns or by meter order (production first, consumption second).
            productionMeter = None
            consumptionMeter = None
            for meter in metersData:
                # Some firmware versions include measurementType directly
                mtype = meter.get('measurementType', '')
                if mtype == 'production':
                    productionMeter = meter
                elif mtype in ('total-consumption', 'net-consumption'):
                    if consumptionMeter is None:  # prefer total-consumption
                        consumptionMeter = meter
            # Fallback: if measurementType not present, use /ivp/meters to identify
            # For now, use positional: first meter = production, second = consumption
            if productionMeter is None and consumptionMeter is None and len(metersData) >= 1:
                productionMeter = metersData[0]
                if len(metersData) >= 2:
                    consumptionMeter = metersData[1]
            dev.updateStateOnServer('metersEnabled', value=True)
            # Parse production meter aggregate values
            if productionMeter is not None:
                self._updateMeterAggregates(dev, productionMeter, 'production')
                self._updatePhaseChannels(dev, productionMeter, 'production')
            # Parse consumption meter aggregate values
            if consumptionMeter is not None:
                self._updateMeterAggregates(dev, consumptionMeter, 'consumption')
                self._updatePhaseChannels(dev, consumptionMeter, 'consumption')
        except Exception as error:
            if self.debugLevel >= 2:
                self.logger.debug(f"Exception parsing meters readings: {error}")
                self.logger.exception("parseMetersReadings Exception")

    def _updateMeterAggregates(self, dev, meter, meterType):
        """Update aggregate (total) meter states for production or consumption."""
        prefix = meterType  # 'production' or 'consumption'
        try:
            voltage = round(meter.get('voltage', 0), 1)
            current = round(meter.get('current', 0), 3)
            pwrFactor = round(meter.get('pwrFactor', 0), 2)
            freq = round(meter.get('freq', 0), 3)
            stateList = [
                {'key': f'{prefix}Voltage', 'value': voltage, 'uiValue': f'{voltage:.1f}'},
                {'key': f'{prefix}Current', 'value': current, 'uiValue': f'{current:.3f}'},
                {'key': f'{prefix}PowerFactor', 'value': pwrFactor, 'uiValue': f'{pwrFactor:.2f}'},
                {'key': f'{prefix}Frequency', 'value': freq, 'uiValue': f'{freq:.3f}'},
            ]
            dev.updateStatesOnServer(stateList)


        except Exception as error:
            if self.debugLevel >= 2:
                self.logger.debug(f"Error updating {prefix} meter aggregates: {error}")

    def _updatePhaseChannels(self, dev, meter, meterType):
        """
        Update per-phase (L1/L2/L3) states from meter channels array.
        Channels are ordered L1, L2, L3 by array index.
        """
        channels = meter.get('channels', [])
        if not channels:
            return
        phaseLabels = ['L1', 'L2', 'L3']
        stateList = []
        for idx, channel in enumerate(channels):
            if idx >= 3:
                break
            phase = phaseLabels[idx]
            try:
                activePower = round(channel.get('activePower', channel.get('instantaneousDemand', 0)), 1)
                voltage = round(channel.get('voltage', 0), 1)
                current = round(channel.get('current', 0), 3)
                apparentPower = round(channel.get('apparentPower', 0), 1)
                pwrFactor = round(channel.get('pwrFactor', 0), 2)
                freq = round(channel.get('freq', 0), 3)
                if meterType == 'production':
                    stateList.append({'key': f'productionWatts{phase}', 'value': activePower, 'uiValue': f'{activePower:.1f}'})
                elif meterType == 'consumption':
                    stateList.append({'key': f'consumptionWatts{phase}', 'value': activePower, 'uiValue': f'{activePower:.1f}'})                # Voltage/current/apparent power - use production meter for these shared values
                if meterType == 'production':
                    stateList.append({'key': f'voltage{phase}', 'value': voltage, 'uiValue': f'{voltage:.1f}'})
                    stateList.append({'key': f'current{phase}', 'value': current, 'uiValue': f'{current:.3f}'})
                    stateList.append({'key': f'apparentPower{phase}', 'value': apparentPower, 'uiValue': f'{apparentPower:.1f}'})
                    stateList.append({'key': f'powerFactor{phase}', 'value': pwrFactor, 'uiValue': f'{pwrFactor:.2f}'})
                    stateList.append({'key': f'frequency{phase}', 'value': freq, 'uiValue': f'{freq:.3f}'})
            except Exception as error:
                if self.debugLevel >= 2:
                    self.logger.debug(f"Error updating phase {phase} for {meterType}: {error}")
            if stateList:
                dev.updateStatesOnServer(stateList)

    def legacyParseStateValues(self, dev, results):
        """
        The parseStateValues() method walks through the dict and assigns the
        corresponding value to each device state.
        """
        if self.debugLevel >= 2:
            self.logger.debug(u"Saving Values method called.")

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
                self.logger.debug("State Image Selector:"+str(dev.displayStateImageSel))

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
            self.logger.debug(u"Saving Values method called.")
            #self.logger.debug(str(self.finalDict))

        try:
            envoyType = dev.states['typeEnvoy']
            unmetered = dev.pluginProps.get('unmetered', False)
            if unmetered:
                envoyType = "Unmetered"
            consumptionWatts =0
            productionWatts =0
            # Check that finalDict contains a production list

            if data is None:
                if self.debugLevel >= 2:
                    self.logger.debug(u"no data found.")
                return

            if "production" in data:
                dev.updateStateOnServer('numberInverters', value=int(data['production'][0]['activeCount']))
            else:
                if self.debugLevel >= 2:
                    self.logger.debug(u"no Production result found.")
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
                        self.logger.debug(u"no Production 2 result found.")
                    dev.updateStateOnServer('productionWattsNow', value=0)
                    dev.updateStateOnServer('production7days',value=0)
                    dev.updateStateOnServer('productionWattsToday',value=0)

            if envoyType == "Unmetered":
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
                elif "production" in data:
                    dev.updateStateOnServer("productionWattsNow", value=int(data["production"][0]["wNow"]))
                    productionWatts = int(data["production"][0]["wNow"])

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
                            self.logger.debug(u'No netConsumption being reporting.....Calculating....')
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
                    #     self.logger.debug(u'No netConsumption being reporting.....Calculating....')
                    # # Calculate?
                    # #
                    # netConsumption = int(consumptionWatts) - int(productionWatts)
                    # dev.updateStateOnServer('netConsumptionWattsNow', value=int(netConsumption))

            else:
                if self.debugLevel >= 2:
                    self.logger.debug(u"no Consumption result found.")

            if envoyType == "Metered":
                if "storage" in data:
                    dev.updateStateOnServer('storageActiveCount', value=int(data['storage'][0]['activeCount']))
                    dev.updateStateOnServer('storageWattsNow', value=int(data['storage'][0]['wNow']))
                    dev.updateStateOnServer('storageState', value=data['storage'][0]['state'])
                    #dev.updateStateOnServer('storagePercentFull', value=int(self.finalDict['storage'][0]['percentFull']))
            else:
                if self.debugLevel >= 2:
                    self.logger.debug(u"no Storage result found.")
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
                self.logger.debug(u"State Image Selector:"+str(dev.displayStateImageSel))

            ##
            self.setproductionMax(dev, productionWatts)


            if envoyType == "Metered":

                if productionWatts >= consumptionWatts and (dev.states['powerStatus']=='importing' or dev.states['powerStatus']=='offline'):
                    #Generating more Power - and a change
                    # If Generating Power - but device believes importing - recent change unpdate to refleect
                    if self.debugLevel >= 2:
                        self.logger.debug(u'**CHANGED**: Exporting Power')

                    dev.updateStateOnServer('powerStatus', value = 'exporting', uiValue='Exporting Power')
                    dev.updateStateOnServer('generatingPower', value=True)
                    dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)
                    if self.debugLevel >= 2:
                        self.logger.debug("State Image Selector:" + str(dev.displayStateImageSel))

                if productionWatts < consumptionWatts and (dev.states['powerStatus'] == 'exporting' or dev.states['powerStatus']=='offline'):
                    #Must be opposite or and again a change only
                    if self.debugLevel >= 2:
                        self.logger.debug(u'**CHANGED**: Importing power')
                    dev.updateStateOnServer('powerStatus', value='importing', uiValue='Importing Power')
                    dev.updateStateOnServer('generatingPower', value=False)
                    dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)
                    if self.debugLevel >= 2:
                        self.logger.debug(u"State Image Selector:" + str(dev.displayStateImageSel))
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
                        self.logger.debug("State Image Selector:" + str(dev.displayStateImageSel))
                elif productionWatts <= 0:
                    dev.updateStateOnServer('generatingPower', value=False, uiValue="No Power Production")
                    dev.updateStateOnServer('powerStatus', value="idle", uiValue="Not Producing Energy")
                    dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)

            for costdev in indigo.devices.iter('self.EnphaseEnvoyCostDevice'):
                if self.debugLevel >2:
                    self.logger.debug(u'Updating Cost Device')
                self.updateCostDevice(dev, costdev)

            for battdev in indigo.devices.iter('self.EnphaseEnvoyBatteryDevice'):
                if self.debugLevel > 2:
                    self.logger.debug(u'Updating Battery Device')
                self.updateBatteryDevice(dev, battdev)

        except Exception as error:
             if self.debugLevel >= 2:
                 self.errorLog(u"Saving Values errors:"+str(error) + str(error) )
                 self.logger.exception("Saving Values Exception")

    def updateCostDevice(self, dev, costdev):
        if self.debugLevel >= 2:
            self.logger.debug(u'updateCostDevice Run')
        # get current Tarrif
        try:
            tariffkwhconsumption = float(costdev.pluginProps['envoyTariffkWhConsumption'])
            tariffkwhproduction = float(costdev.pluginProps['envoyTariffkWhProduction'])
        except Exception as error:
            if self.debugLevel >= 2:
                self.logger.debug(
                    u'error with Tarriff kwh,please update device settings. Defaulting to $1.0/kwh:' + str(error))
            tariffkwhproduction = 1.0
            tariffkwhconsumption = 1.0

        try:
            productionkwhToday = round(float(dev.states['productionWattsToday']) / 1000, 3)
            productionTarrifToday = round(productionkwhToday * tariffkwhproduction, 2)

            consumptionkwhToday = round(float(dev.states['consumptionWattsToday']) / 1000, 3)
            consumptionTarrifToday = round(consumptionkwhToday * tariffkwhconsumption, 2)

            productionkwh7days = round(float(dev.states['production7days']) / 1000, 3)
            productionTarrif7days = round(productionkwh7days * tariffkwhproduction, 2)

            consumptionkwh7days = round(float(dev.states['consumption7days']) / 1000, 3)
            consumptionTarrif7days = round(consumptionkwh7days * tariffkwhconsumption, 2)

            productionkwhLifetime = round(float(dev.states['productionwhLifetime']) / 1000, 3)
            productionTarrifLifetime = round(productionkwhLifetime * tariffkwhproduction, 2)

            consumptionkwhLifetime = round(float(dev.states['consumptionwhLifetime']) / 1000, 3)
            consumptionTarrifLifetime = round(consumptionkwhLifetime * tariffkwhconsumption, 2)

            netconsumptionkwhLifetime = round(float(dev.states['netconsumptionwhLifetime']) / 1000, 3)
            netconsumptionTarrifLifetime = round(netconsumptionkwhLifetime * tariffkwhconsumption, 2)

            # change to cost.
            netTarrif7days = round(productionTarrif7days - consumptionTarrif7days, 2)
            netTarrifToday = round(productionTarrifToday - consumptionTarrifToday, 2)
            netkw7Days = round(productionkwh7days - consumptionkwh7days, 3)
            netkwToday = round(productionkwhToday - consumptionkwhToday, 3)

            update_time = t.strftime("%m/%d/%Y at %H:%M")

            stateList = [
                {'key': 'productionTarrifToday', 'value': '${:,.2f}'.format(productionTarrifToday)},
                {'key': 'productionkWToday', 'value': productionkwhToday, 'uiValue': f'{productionkwhToday:.3f}'},
                {'key': 'consumptionTarrifToday', 'value': '${:,.2f}'.format(consumptionTarrifToday)},
                {'key': 'consumptionkWToday', 'value': consumptionkwhToday, 'uiValue': f'{consumptionkwhToday:.3f}'},
                {'key': 'productionTarrif7days', 'value': '${:,.2f}'.format(productionTarrif7days)},
                {'key': 'productionkW7days', 'value': productionkwh7days, 'uiValue': f'{productionkwh7days:.3f}'},
                {'key': 'consumptionTarrif7days', 'value': '${:,.2f}'.format(consumptionTarrif7days)},
                {'key': 'consumptionkW7days', 'value': consumptionkwh7days, 'uiValue': f'{consumptionkwh7days:.3f}'},
                {'key': 'productionTarrifLifetime', 'value': '${:,.2f}'.format(productionTarrifLifetime)},
                {'key': 'productionkwhLifetime', 'value': productionkwhLifetime,
                 'uiValue': f'{productionkwhLifetime:.3f}'},
                {'key': 'consumptionTarrifLifetime', 'value': '${:,.2f}'.format(consumptionTarrifLifetime)},
                {'key': 'consumptionkwhLifetime', 'value': consumptionkwhLifetime,
                 'uiValue': f'{consumptionkwhLifetime:.3f}'},
                {'key': 'netconsumptionTarrifLifetime', 'value': '${:,.2f}'.format(netconsumptionTarrifLifetime)},
                {'key': 'netconsumptionkwhLifetime', 'value': netconsumptionkwhLifetime,
                 'uiValue': f'{netconsumptionkwhLifetime:.3f}'},
                {'key': 'netkWToday', 'value': netkwToday, 'uiValue': f'{netkwToday:.3f}'},
                {'key': 'netkW7days', 'value': netkw7Days, 'uiValue': f'{netkw7Days:.3f}'},
                {'key': 'netTarrifToday', 'value': '${:,.2f}'.format(netTarrifToday)},
                {'key': 'netTarrif7days', 'value': '${:,.2f}'.format(netTarrif7days)},
                {'key': 'deviceLastUpdated', 'value': update_time},
            ]
            costdev.updateStatesOnServer(stateList)
            return

        except Exception as error:
            self.logger.exception(u'Exception within Cost Device Calculation:' + str(error))
            return





    def setStatestonil(self, dev):
        if self.debugLevel >= 2:
            self.logger.debug(u'setStates to nil run')



    def generatePanelDevices(self, valuesDict, typeId, devId):
        self.WaitInterval = 180
        panel_thread = threading.Thread(target=self.generatepanels_thread, args=[devId])
        panel_thread.start()

    def generatepanels_thread(self, devId):
        if self.debugLevel >= 2:
            self.logger.debug(u'generate Panels run')
        try:
            #delete all panel devices first up
            dev = indigo.devices[devId]
            if self.debugLevel>=2:
                self.logger.debug(u'Folder ID'+str(dev.folderId))
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
            self.checkThePanels_New(dev, self.thePanels)


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
            self.logger.debug(u'Delete Panels run')

        try:
            # delete all panel devices first up
            for dev in indigo.devices.iter('self.EnphasePanelDevice'):
                indigo.device.delete(dev.id)
                if self.debugLevel > 2:
                    self.logger.debug(u'Deleting Device' + str(dev.id))
        except Exception as error:
            self.errorLog(u'error within delete panels' + str(error))

    def refreshDataAction(self, valuesDict):
        """
        The refreshDataAction() method refreshes data for all devices based on
        a plugin menu call.
        """
        if self.debugLevel >= 2:
            self.logger.debug(u"refreshDataAction() method called.")
        self.refreshData()
        return True

    def refreshData(self):
        """
        The refreshData() method controls the updating of all plugin
        devices.
        """
        if self.debugLevel >= 2:
            self.logger.debug(u"refreshData() method called.")

        try:
            # Check to see if there have been any devices created.
            if indigo.devices.iter(filter="self"):
                if self.debugLevel >= 2:
                    self.logger.debug(u"Updating data...")

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
            self.logger.debug(u"Type of Envoy Checking...: {0}".format(dev.name))
        data = self.getTheData(dev)
        if data is not None:
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

    def refreshDataForDev( self, dev):
        if dev.configured:
            if self.debugLevel >= 2:
                self.logger.debug(u"Found configured device: {0}".format(dev.name))
            if dev.enabled:
                if self.debugLevel >= 2:
                    self.logger.debug(u"   {0} is enabled.".format(dev.name))
                timeDifference = int(t.time() - t.mktime(dev.lastChanged.timetuple()))
                if self.debugLevel >= 2:
                    self.logger.debug(dev.name + u": Time Since Device Update = " + str(timeDifference))
                    # self.errorLog(str(dev.lastChanged))
                # Get the data.
                # If device is offline wait for 60 seconds until rechecking

                if dev.states['typeEnvoy']== "" or dev.states['typeEnvoy']=="unknown":
                    if self.debugLevel >= 2:
                        self.logger.debug(u"Type of Envoy Checking...: {0}".format(dev.name))
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
                        self.logger.debug(u"Offline: Refreshing device: {0}".format(dev.name))
                    data = self.gettheDataChoice(dev)

                    self.parseStateValues(dev, data)
                elif dev.states['deviceIsOnline']:
                    if self.debugLevel >= 2:
                        self.logger.debug(u"Online: Refreshing device: {0}".format(dev.name))
                    data = self.gettheDataChoice(dev)
                    self.parseStateValues(dev, data)
                    #self._applyPdmEnergy(dev)   Meters seems better result.  Not using PDM.
                    self._pollPowerProductionStatus(dev)
                    # Fetch and parse per-phase meter readings for metered systems
                    if dev.states.get('typeEnvoy') == "Metered":
                        metersData = self.getMetersReadings(dev)
                        self.parseMetersReadings(dev, metersData)
            else:
                if self.debugLevel >= 2:
                    self.logger.debug(u"    Disabled: {0}".format(dev.name))

    def legacyRefreshEnvoy(self,dev):
        if dev.configured:
            if self.debugLevel >= 2:
                self.logger.debug(u"Found configured device: {0}".format(dev.name))

            if dev.enabled:
                if self.debugLevel >= 2:
                    self.logger.debug(u"   {0} is enabled.".format(dev.name))
                timeDifference = int(t.time() - t.mktime(dev.lastChanged.timetuple()))
                if self.debugLevel >= 2:
                    self.logger.debug(dev.name + u": Time Since Device Update = " + str(timeDifference))
                    # self.errorLog(str(dev.lastChanged))
                # Get the data.
                # If device is offline wait for 60 seconds until rechecking
                if dev.states['deviceIsOnline'] == False and timeDifference >= 180:
                    if self.debugLevel >= 2:
                        self.logger.debug(u"Offline: Refreshing device: {0}".format(dev.name))
                    results = self.legacyGetTheData(dev)
                # if device online normal time

                if dev.states['deviceIsOnline']:
                    if self.debugLevel >= 2:
                        self.logger.debug(u"Online: Refreshing device: {0}".format(dev.name))
                    results = self.legacyGetTheData(dev)
                    #ignore panel level data until later
                    #self.PanelDict = self.getthePanels(dev)
                    # Put the final values into the device states - only if online
                if dev.states['deviceIsOnline']:
                    self.legacyParseStateValues(dev, results)
            else:
                if self.debugLevel >= 2:
                    self.logger.debug(u"    Disabled: {0}".format(dev.name))

    def refreshDataForDevAction(self, valuesDict):
        """
        The refreshDataForDevAction() method refreshes data for a selected device based on
        a plugin menu call.
        """
        if self.debugLevel >= 2:
            self.logger.debug(u"refreshDataForDevAction() method called.")

        dev = indigo.devices[valuesDict.deviceId]

        self.refreshDataForDev(dev)
        return True


    def toggleDebugEnabled(self):
        """
        Toggle debug on/off.
        """
        if self.debugLevel >= 2:
            self.logger.debug(u"toggleDebugEnabled() method called.")
        if not self.debug:
            self.debug = True
            self.pluginPrefs['showDebugInfo'] = True
            indigo.server.log(u"Debugging on.")
            self.logger.debug(u"Debug level: {0}".format(self.debugLevel))

        else:
            self.debug = False
            self.pluginPrefs['showDebugInfo'] = False
            indigo.server.log(u"Debugging off.")

 # ─────────────────────────────────────────────────────────────
    # Battery & Grid Device
    # ─────────────────────────────────────────────────────────────

    def getEnsembleInventory(self, dev):
        """
        Fetch battery inventory from /ivp/ensemble/inventory.
        Returns the JSON array, or None on failure.
        The Envoy device (not the battery device) is used for IP/auth.
        """
        try:
            headers = self.create_headers(dev)
            url = f"http{self.https_flag}://{dev.pluginProps['sourceXML']}/ivp/ensemble/inventory"
            r = self._get(url, headers=headers)
            if r.status_code == 200:
                result = r.json()
                if self.debugLevel >= 2:
                    self.logger.debug(f"Ensemble Inventory Result: {result}")
                return result
            else:
                if self.debugLevel >= 2:
                    self.logger.debug(f"Ensemble Inventory returned status {r.status_code}")
                return None
        except Exception as error:
            if self.debugLevel >= 2:
                self.logger.debug(f"Exception fetching ensemble inventory: {error}")
            return None

    def updateBatteryDevice(self, envoyDev, battDev):
        """
        Fetch battery data from the Envoy API and update the combined
        battery device states. Uses /ivp/ensemble/inventory for per-battery
        details (percentFull, temperature, capacity) and the storage data
        from production.json for aggregate wNow/state.

        envoyDev: the parent EnphaseEnvoyDevice (has IP, auth, storage data)
        battDev:  the EnphaseEnvoyBatteryDevice to update
        """
        if self.debugLevel >= 2:
            self.logger.debug(u'updateBatteryDevice Run')

        try:
            # ── Pull aggregate storage data from the parent Envoy device ──
            storageCount = int(envoyDev.states.get('storageActiveCount', 0))
            storageWattsNow = int(envoyDev.states.get('storageWattsNow', 0))
            storageState = str(envoyDev.states.get('storageState', 'unknown'))

            battDev.updateStateOnServer('batteryCount', value=storageCount)
            battDev.updateStateOnServer('batteryWattsNow', value=storageWattsNow)

            # Determine charge vs discharge from wNow sign
            # Positive wNow = discharging, Negative = charging (Enphase convention)
            if storageWattsNow > 0:
                battDev.updateStateOnServer('batteryChargeWatts', value=0)
                battDev.updateStateOnServer('batteryDischargeWatts', value=storageWattsNow)
            elif storageWattsNow < 0:
                battDev.updateStateOnServer('batteryChargeWatts', value=abs(storageWattsNow))
                battDev.updateStateOnServer('batteryDischargeWatts', value=0)
            else:
                battDev.updateStateOnServer('batteryChargeWatts', value=0)
                battDev.updateStateOnServer('batteryDischargeWatts', value=0)

            # Map storage state to battery state
            stateMap = {
                'idle': 'idle',
                'charging': 'charging',
                'discharging': 'discharging',
                'full': 'idle',
                'Offline': 'offline',
                'No Data': 'unknown',
            }
            battState = stateMap.get(storageState, 'unknown')
            battDev.updateStateOnServer('batteryState', value=battState)

            # ── Calculate grid import/export from parent Envoy ──
            netConsumption = int(envoyDev.states.get('netConsumptionWattsNow', 0))

            # netConsumption: positive = importing from grid, negative = exporting to grid
            gridImport = max(0, netConsumption)
            gridExport = max(0, -netConsumption)
            battDev.updateStateOnServer('gridImportWatts', value=gridImport)
            battDev.updateStateOnServer('gridExportWatts', value=gridExport)
            battDev.updateStateOnServer('gridNetWatts', value=netConsumption)

            # ── Fetch detailed battery inventory from /ivp/ensemble/inventory ──
            inventoryData = self.getEnsembleInventory(envoyDev)

            totalCapacityWh = 0
            totalPercentFull = 0
            totalTemp = 0
            maxCellTemp = 0
            batteryDeviceCount = 0
            serialNumbers = []
            firmwareVersions = set()
            allCommunicating = True
            allOperating = True

            if inventoryData is not None:
                for entry in inventoryData:
                    entryType = entry.get('type', '').upper()
                    if entryType != 'ENCHARGE':
                        continue
                    devices = entry.get('devices', [])
                    for battery in devices:
                        batteryDeviceCount += 1
                        serialNumbers.append(str(battery.get('serial_num', 'unknown')))
                        fw = battery.get('img_pnum_running', '')
                        if fw:
                            firmwareVersions.add(fw)
                        capacity = int(battery.get('encharge_capacity', 0))
                        totalCapacityWh += capacity
                        pctFull = int(battery.get('percentFull', 0))
                        totalPercentFull += pctFull
                        temp = int(battery.get('temperature', 0))
                        totalTemp += temp
                        cellTemp = int(battery.get('maxCellTemp', 0))
                        if cellTemp > maxCellTemp:
                            maxCellTemp = cellTemp
                        if not battery.get('communicating', False):
                            allCommunicating = False
                        if not battery.get('operating', False):
                            allOperating = False

            avgPercentFull = 0
            if batteryDeviceCount > 0:
                avgPercentFull = int(totalPercentFull / batteryDeviceCount)
                avgTemp = int(totalTemp / batteryDeviceCount)
                battDev.updateStateOnServer('batteryPercentFull', value=avgPercentFull,
                                            uiValue=f"{avgPercentFull}%")
                battDev.updateStateOnServer('batteryTemperature', value=avgTemp)
                battDev.updateStateOnServer('batteryMaxCellTemp', value=maxCellTemp)
                battDev.updateStateOnServer('batteryCount', value=batteryDeviceCount)
                battDev.updateStateOnServer('batteryCommunicating', value=allCommunicating)
                battDev.updateStateOnServer('batteryOperating', value=allOperating)
                battDev.updateStateOnServer('batterySerialNumbers',
                                            value=', '.join(serialNumbers))
                battDev.updateStateOnServer('batteryFirmware',
                                            value=', '.join(sorted(firmwareVersions)))
            else:
                battDev.updateStateOnServer('batteryPercentFull', value=0, uiValue="N/A")
                battDev.updateStateOnServer('batteryTemperature', value=0)
                battDev.updateStateOnServer('batteryMaxCellTemp', value=0)
                battDev.updateStateOnServer('batteryCommunicating', value=False)
                battDev.updateStateOnServer('batteryOperating', value=False)
                battDev.updateStateOnServer('batterySerialNumbers', value='')
                battDev.updateStateOnServer('batteryFirmware', value='')

            battDev.updateStateOnServer('batteryTotalCapacityWh', value=totalCapacityWh)
            battDev.updateStateOnServer('batteryTotalkW',
                                        value=round(totalCapacityWh / 1000, 2))
            battDev.updateStateOnServer('batteryWhNow',
                                        value=int(totalCapacityWh * avgPercentFull / 100) if batteryDeviceCount > 0 else 0)

            # ── Grid status ──
            if envoyDev.states.get('deviceIsOnline', False):
                powerStatus = envoyDev.states.get('powerStatus', 'unknown')
                if powerStatus == 'exporting':
                    battDev.updateStateOnServer('gridStatus', value='Exporting')
                elif powerStatus == 'importing':
                    battDev.updateStateOnServer('gridStatus', value='Importing')
                elif powerStatus == 'offline':
                    battDev.updateStateOnServer('gridStatus', value='Offline')
                else:
                    battDev.updateStateOnServer('gridStatus', value='Connected')
            else:
                battDev.updateStateOnServer('gridStatus', value='Unknown')

            # ── Update timestamps and online status ──
            battDev.updateStateOnServer('deviceIsOnline', value=True, uiValue="Online")
            update_time = t.strftime("%m/%d/%Y at %H:%M")
            battDev.updateStateOnServer('deviceLastUpdated', value=update_time)


            # ── Fetch and display tariff/storage settings ──
            tariffData = self._getTariffData(envoyDev)
            if tariffData is not None:
                try:
                    tariffObj = tariffData.get('tariff', tariffData)
                    storageSettings = tariffObj.get('storage_settings', {})
                    if storageSettings:
                        currentMode = storageSettings.get('mode', 'unknown')
                        chargeFromGrid = storageSettings.get('charge_from_grid', False)
                        reservedSoc = storageSettings.get('reserved_soc', 0)
                        battDev.updateStateOnServer('storageMode', value=str(currentMode))
                        battDev.updateStateOnServer('chargeFromGrid', value=bool(chargeFromGrid))
                        battDev.updateStateOnServer('reserveSOC', value=int(float(reservedSoc)))
                except Exception as tariffErr:
                    if self.debugLevel >= 2:
                        self.logger.debug(f"Error parsing tariff storage settings: {tariffErr}")

            # ── Update state image based on battery activity ──
            if battState == 'charging':
                battDev.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)
            elif battState == 'discharging':
                battDev.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)
            elif battState == 'idle':
                battDev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)
            else:
                battDev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)

        except Exception as error:
            if self.debugLevel >= 2:
                self.logger.debug(f"Exception updating battery device: {error}")
                self.logger.exception("updateBatteryDevice Exception")

    def refreshBatteryDataAction(self, pluginAction):
        """Action callback: Refresh Battery & Grid Data for selected battery device."""
        battDev = indigo.devices[pluginAction.deviceId]
        if self.debugLevel >= 2:
            self.logger.debug(f"refreshBatteryDataAction called for {battDev.name}")
        # Find the parent EnphaseEnvoyDevice to pull data from
        for envoyDev in indigo.devices.iter('self.EnphaseEnvoyDevice'):
            if envoyDev.enabled and envoyDev.states.get('deviceIsOnline', False):
                self.updateBatteryDevice(envoyDev, battDev)
                return
        self.logger.info("No online EnphaseEnvoyDevice found to refresh battery data from.")

# ─────────────────────────────────────────────────────────────
    # Battery Control Actions (Tariff-based)
    # ─────────────────────────────────────────────────────────────

    def _getParentEnvoyDev(self):
        """Find the first enabled, online EnphaseEnvoyDevice to use for API calls."""
        for envoyDev in indigo.devices.iter('self.EnphaseEnvoyDevice'):
            if envoyDev.enabled and envoyDev.states.get('deviceIsOnline', False):
                return envoyDev
        return None

    def _getTariffData(self, envoyDev):
        """
        Fetch current tariff data from /admin/lib/tariff.
        Returns the JSON dict, or None on failure.
        """
        try:
            headers = self.create_headers(envoyDev)
            if not headers and self.using_token:
                self.logger.error("No auth token available for tariff request.")
                return None
            url = f"http{self.https_flag}://{envoyDev.pluginProps['sourceXML']}{ENVOY_TARIFF_PATH}"
            r = self._get(url, headers=headers)
            if r.status_code == 200:
                result = r.json()
                if self.debugLevel >= 2:
                    self.logger.debug(f"Tariff Data Result: {result}")
                return result
            else:
                if self.debugLevel >= 2:
                    self.logger.debug(f"Tariff endpoint returned status {r.status_code}")
                return None
        except Exception as error:
            if self.debugLevel >= 2:
                self.logger.debug(f"Exception fetching tariff data: {error}")
            return None

    def _putTariffData(self, envoyDev, tariffData):
        """
        PUT updated tariff data to /admin/lib/tariff.
        Returns True on success, False on failure.
        Based on pyenphase: PUT /admin/lib/tariff with {"tariff": <tariff_object>}
        """
        try:
            headers = self.create_headers(envoyDev)
            if not headers and self.using_token:
                self.logger.error(
                    "No auth token configured. "
                    "Battery control requires a JWT token (firmware 7.x+)."
                )
                return False

            ip_address = envoyDev.pluginProps.get('sourceXML', '')
            if not ip_address:
                self.logger.error(f"No IP address configured for device: {envoyDev.name}")
                return False

            url = f"http{self.https_flag}://{ip_address}{ENVOY_TARIFF_PATH}"
            payload = json.dumps({"tariff": tariffData})
            headers['Content-Type'] = 'application/json'

            if self.debugLevel >= 2:
                self.logger.debug(f"PUT {url}")

            host = urlsplit(url).netloc
            is_new = host not in self.session_cache

            session = self.session_cache[host]

            if self.debugLevel >= 2:
                if is_new:
                    self.logger.debug(f"[HTTP] Created NEW session {hex(id(session))} for host {host}")
                else:
                    self.logger.debug(f"[HTTP] Re-using session {hex(id(session))} for host {host}")
                self.logger.debug(
                    f"[HTTP] PUT {url}\n"
                    f"       timeout={self.prefServerTimeout!r}\n"
                    f"       headers={headers}\n"
                    f"       cookies={session.cookies.get_dict()}"
                )

            r = session.put(url, data=payload, headers=headers,
                            timeout=self.prefServerTimeout, allow_redirects=True)
            if self.debugLevel >= 2:
                self.logger.debug(f"[HTTP] {host} → {r.status_code}  (session {hex(id(session))})")

            if r.status_code == 200:
                return True
            elif r.status_code in (401, 403):
                self.logger.info(
                    f"Authorization failed for tariff update on {envoyDev.name}. "
                    f"HTTP {r.status_code}. "
                    f"This endpoint may require an installer-level JWT token."
                )
                return False
            else:
                self.logger.error(
                    f"Failed to update tariff for {envoyDev.name}. "
                    f"HTTP {r.status_code}: {r.text}"
                )
                return False

        except requests.exceptions.Timeout:
            self.logger.error(f"Timeout updating tariff for: {envoyDev.name}")
            return False
        except requests.exceptions.ConnectionError:
            self.logger.error(f"Connection error updating tariff for: {envoyDev.name}")
            return False
        except Exception as err:
            self.logger.error(f"Error updating tariff for {envoyDev.name}: {err}")
            return False

    def _setStorageMode(self, battDev, mode):
        """
        Set storage mode via /admin/lib/tariff PUT.
        mode: 'self-consumption', 'savings', or 'backup'
        """
        envoyDev = self._getParentEnvoyDev()
        if not envoyDev:
            self.logger.error("No online EnphaseEnvoyDevice found for battery control.")
            return False

        tariffData = self._getTariffData(envoyDev)
        if tariffData is None:
            self.logger.error("Could not fetch current tariff data for storage mode change.")
            return False

        # Navigate to storage_settings and update mode
        try:
            if 'tariff' in tariffData:
                tariffObj = tariffData['tariff']
            else:
                tariffObj = tariffData

            if 'storage_settings' not in tariffObj:
                self.logger.error("No storage_settings found in tariff data. Battery may not be configured.")
                return False

            tariffObj['storage_settings']['mode'] = mode

            if self._putTariffData(envoyDev, tariffObj):
                indigo.server.log(f"Storage mode successfully set to '{mode}' for {battDev.name}")
                battDev.updateStateOnServer('storageMode', value=mode)
                return True
            return False

        except Exception as error:
            self.logger.error(f"Error setting storage mode: {error}")
            return False

    def _setChargeFromGrid(self, battDev, enable):
        """
        Enable or disable charge from grid via /admin/lib/tariff PUT.
        """
        envoyDev = self._getParentEnvoyDev()
        if not envoyDev:
            self.logger.error("No online EnphaseEnvoyDevice found for battery control.")
            return False

        tariffData = self._getTariffData(envoyDev)
        if tariffData is None:
            self.logger.error("Could not fetch current tariff data for charge-from-grid change.")
            return False

        try:
            if 'tariff' in tariffData:
                tariffObj = tariffData['tariff']
            else:
                tariffObj = tariffData

            if 'storage_settings' not in tariffObj:
                self.logger.error("No storage_settings found in tariff data. Battery may not be configured.")
                return False

            tariffObj['storage_settings']['charge_from_grid'] = enable

            action_label = "Enabled" if enable else "Disabled"
            if self._putTariffData(envoyDev, tariffObj):
                indigo.server.log(f"Successfully {action_label.lower()} charge from grid for {battDev.name}")
                battDev.updateStateOnServer('chargeFromGrid', value=enable)
                return True
            return False

        except Exception as error:
            self.logger.error(f"Error setting charge from grid: {error}")
            return False

    def _setReserveSOC(self, battDev, value):
        """
        Set the battery reserve state of charge (%) via /admin/lib/tariff PUT.
        value: integer 0-100
        """
        envoyDev = self._getParentEnvoyDev()
        if not envoyDev:
            self.logger.error("No online EnphaseEnvoyDevice found for battery control.")
            return False

        # Validate range
        value = max(0, min(100, int(value)))

        tariffData = self._getTariffData(envoyDev)
        if tariffData is None:
            self.logger.error("Could not fetch current tariff data for reserve SOC change.")
            return False

        try:
            if 'tariff' in tariffData:
                tariffObj = tariffData['tariff']
            else:
                tariffObj = tariffData

            if 'storage_settings' not in tariffObj:
                self.logger.error("No storage_settings found in tariff data. Battery may not be configured.")
                return False

            tariffObj['storage_settings']['reserved_soc'] = round(float(value), 1)

            if self._putTariffData(envoyDev, tariffObj):
                indigo.server.log(f"Reserve SOC successfully set to {value}% for {battDev.name}")
                battDev.updateStateOnServer('reserveSOC', value=value)
                return True
            return False

        except Exception as error:
            self.logger.error(f"Error setting reserve SOC: {error}")
            return False

    # ── Battery Action Callbacks ──

    def setStorageModeSelfConsumptionAction(self, pluginAction):
        """Action callback: Set storage mode to self-consumption."""
        battDev = indigo.devices[pluginAction.deviceId]
        self.logger.info(f"Setting storage mode to self-consumption for {battDev.name}")
        self._setStorageMode(battDev, 'self-consumption')

    def setStorageModeSavingsAction(self, pluginAction):
        """Action callback: Set storage mode to savings."""
        battDev = indigo.devices[pluginAction.deviceId]
        self.logger.info(f"Setting storage mode to savings for {battDev.name}")
        self._setStorageMode(battDev, 'savings')

    def setStorageModeFullBackupAction(self, pluginAction):
        """Action callback: Set storage mode to full backup."""
        battDev = indigo.devices[pluginAction.deviceId]

        self.logger.info(f"Setting storage mode to full backup for {battDev.name}")
        self._setStorageMode(battDev, 'backup')

    def enableChargeFromGridAction(self, pluginAction):
        """Action callback: Enable charge from grid."""
        battDev = indigo.devices[pluginAction.deviceId]

        self.logger.info(f"Enabling charge from grid for {battDev.name}")
        self._setChargeFromGrid(battDev, True)

    def disableChargeFromGridAction(self, pluginAction):
        """Action callback: Disable charge from grid."""
        battDev = indigo.devices[pluginAction.deviceId]

        self.logger.info(f"Disabling charge from grid for {battDev.name}")
        self._setChargeFromGrid(battDev, False)

    def setReserveSOCAction(self, pluginAction):
        """Action callback: Set battery reserve SOC percentage."""
        battDev = indigo.devices[pluginAction.deviceId]

        try:
            reservePercent = int(pluginAction.props.get('reservePercent', 20))
        except (ValueError, TypeError):
            self.logger.error("Invalid reserve percentage value. Must be a number 0-100.")
            return
        self.logger.info(f"Setting reserve SOC to {reservePercent}% for {battDev.name}")
        self._setReserveSOC(battDev, reservePercent)
