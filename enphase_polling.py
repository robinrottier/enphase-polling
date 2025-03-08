#!/usr/bin/env python
# -*- coding: utf-8 -*-

# This file is based on part of Enphase-API <https://github.com/Matthew1471/Enphase-API>
# Copyright (C) 2023 Matthew1471!
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 3 as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
This example provides functionality to interact with the Enphase® IQ Gateway API for monitoring
solar energy production and consumption data on the command line.

The functions in this module allow you to:
- Establish a secure gateway session
- Fetch production, consumption, and storage status from Enphase® IQ Gateway devices
- Retrieve human-readable power values
- Write all the retreived data to a MQTT store for inspection there or onward processing
- Sits in a loop refreshing data every minute (although will not change that often on the envoy itself)
"""

import datetime # We manipulate dates and times.
import json     # This script makes heavy use of JSON parsing.
import locale   # We play with encodings so it's good to check what we are set to support.
import os.path  # We check whether a file exists.
import sys
import time      # We check whether we are running on Windows® or not.

# paha mqtt client for publishing to some broker
# if it fails: pip install paho.mqtt

import paho.mqtt as mqttLib
import paho.mqtt.client as mqttClient

# All the shared Enphase® functions are in these packages.
from enphase_api.cloud.authentication import Authentication
from enphase_api.local.gateway import Gateway


def get_human_readable_power(watts, in_hours = False):
    """
    Convert power value to a human-readable format.

    Args:
        watts (float):
            Power value in watts.
        in_hours (bool, optional):
            If True, append 'h' to indicate hours. Default is False.

    Returns:
        str:
            Human-readable power value with unit (W or kW).
    """
    # Is the significant number of watts (i.e. positive or negative number) less than 1,000?
    if abs(round(watts)) < 1000:
        # Report the number in watts (rounded to the nearest number).
        return f'{watts:.0f} W{"h" if in_hours else ""}'

    # Divide the number by a thousand and report it in kW (to 2 decimal places).
    return f'{watts/1000:.2f} kW{"h" if in_hours else ""}'

def get_secure_gateway_session(credentials):
    """
    Establishes a secure session with the Enphase® IQ Gateway API.

    This function manages the authentication process to establish a secure session with
    an Enphase® IQ Gateway.

    It handles JWT validation, token acquisition (if required) and initialises
    the Gateway API wrapper for subsequent interactions.

    It also downloads and stores the certificate from the gateway for secure communication.

    Args:
        credentials (dict): A dictionary containing the required credentials.

    Returns:
        Gateway: An initialised Gateway API wrapper object for interacting with the gateway.

    Raises:
        ValueError: If authentication fails or if required credentials are missing.
    """

    # Do we have a valid JSON Web Token (JWT) to be able to use the service?
    if not (credentials.get('gateway_token')
                and Authentication.check_token_valid(
                    token=credentials['gateway_token'],
                    gateway_serial_number=credentials.get('gateway_serial_number'))):
        # It is not valid so clear it.
        credentials['gateway_token'] = None

    # Do we still not have a Token?
    if not credentials.get('gateway_token'):
        # Do we have a way to obtain a token?
        if credentials.get('enphase_username') and credentials.get('enphase_password'):
            # Create a Authentication object.
            authentication = Authentication()

            # Authenticate with Entrez (French for "Access").
            if not authentication.authenticate(
                username=credentials['enphase_username'],
                password=credentials['enphase_password']):
                raise ValueError('Failed to login to Enphase® Authentication server ("Entrez")')

            # Does the user want to target a specific gateway or all uncommissioned ones?
            if credentials.get('gateway_serial_number'):
                # Get a new gateway specific token (installer = short-life, owner = long-life).
                credentials['gateway_token'] = authentication.get_token_for_commissioned_gateway(
                    gateway_serial_number=credentials['gateway_serial_number']
                )
            else:
                # Get a new uncommissioned gateway specific token.
                credentials['gateway_token'] = authentication.get_token_for_uncommissioned_gateway()

            # Update the file to include the modified token.
            with open('configuration/local_credentials.json', mode='w', encoding='utf-8') as json_file:
                json.dump(credentials, json_file, indent=4)
        else:
            # Let the user know why the program is exiting.
            raise ValueError('Unable to login to the gateway (bad, expired or missing token in credentials.json).')

    # Did the user override the library default hostname to the Gateway?
    host = credentials.get('gateway_host')

    # Download and store the certificate from the gateway so all future requests are secure.
    if credentials.get('gateway_trust') == "false":
        # dotn trust gateway ssl
        if os.path.exists('configuration/gateway.cer'):
            os.remove('configuration/gateway.cer')
    else:
       if not os.path.exists('configuration/gateway.cer'):
           Gateway.trust_gateway(host)

    # Instantiate the Gateway API wrapper (with the default library hostname if None provided).
    gateway = Gateway(host)

    # Are we not able to login to the gateway?
    if not gateway.login(credentials['gateway_token']):
        # Let the user know why the program is exiting.
        raise ValueError('Unable to login to the gateway (bad, expired or missing token in credentials.json).')

    # Return the initialised gateway object.
    return gateway

class MyMqttClient:
    mqtt_root=""
    mqtt_client=None
    mqtt_cache=dict()
    
    def clear_cache(self):
        self.mqtt_cache=dict()
        
    def publish(self, topic, value):
        fulltopic = self.mqtt_root+"/"+topic    
        #check cache for changed value
        if fulltopic in self.mqtt_cache:
            if self.mqtt_cache[fulltopic]==value:
                return # no change - do nothing
        self.mqtt_client.publish(fulltopic,value)
        # write to cache
        self.mqtt_cache[fulltopic]=value
        
    def publish_time(self, topic):
        time_format="%Y-%m-%d %H:%M:%S"
        self.publish(topic, time.strftime(time_format))
        
    def publish_obj(self, topic, obj):    
        if isinstance(obj, dict):
            for k in obj:
                v = obj[k]
                self.publish_obj(f"{topic}/{k}", v)
        elif isinstance(obj, list):
            k=0
            for v in obj:
                self.publish_obj(f"{topic}/{k}", v)
                k=k+1
        else:
            self.publish(topic, obj)

    def start(self, credentials):
        if mqttLib.__version__[0] > '1':
            self.mqtt_client = mqttClient.Client(mqttClient.CallbackAPIVersion.VERSION1, credentials['mqtt_clientid'])
        else:
            self.mqtt_client = mqttClient.Client(credentials['mqtt_clientid'])
        self.mqtt_client.on_connect = self.on_connect
        self.mqtt_client.on_connect_failed = self.on_connect_failed
        self.mqtt_client.on_disconnect = self.on_disconnect
        self.mqtt_client.on_publish = self.on_publish
        self.mqtt_client.username_pw_set(credentials["mqtt_username"], credentials["mqtt_password"])
        self.mqtt_client.connect(credentials['mqtt_broker'], int(credentials['mqtt_port']))
        self.mqtt_client.loop_start()

        # save root path for all publishes
        self.mqtt_root = credentials['mqtt_root']

    def on_connect(self, client, userdata, flags, rc):
        print(f"mqtt connected: {rc}")
    
    def on_connect_failed(self, client, userdata, flags, rc):
        print(f"mqtt connect failed: {rc}")
    
    def on_disconnect(self, client, userdata, rc):
        print(f"mqtt disconnected: {rc}")
    
    def on_publish(self, cient,userdata,mid):
        #print("mqtt published")
        pass
    
mqtt = MyMqttClient()

def process(credentials, forceRefresh=False):
    
    now = time.time()
    
    # Use a secure gateway initialisation flow.
    gateway = get_secure_gateway_session(credentials)
    
   
    # We can force the gateway to poll the inverters early
    # (by default it only does this automatically every 5 minutes).
    if forceRefresh:
        gateway.api_call('/installer/pcu_comm_check')

    # Get gateway production, consumption and storage status.
    production_statistics = gateway.api_call('/production.json')
    mqtt.publish_obj("production", production_statistics)

    # The meter status tells us if they are enabled and what mode they are operating in
    # (production for production meters but net-consumption or total-consumption for consumption
    # meters).
    meters_status = gateway.api_call('/ivp/meters')

    # The Production meters can be not present (not Gateway Metered) or individually turned off
    # (and they require a working CT clamp).
    eim_production_w_now = None
    eim_production_wh_today = None
    eim_production_wh_last_seven_days = None

    meter_statistics_production = [meter_status for meter_status in meters_status if meter_status['measurementType'] == 'production'][0]
    if meter_statistics_production['state'] == 'enabled':
        # Get the Production section of the Production Statistics JSON that matches the configured
        # meter mode.
        production_statistics_production_eim = [production_statistic for production_statistic in production_statistics['production'] if production_statistic['type'] == 'eim' and production_statistic['measurementType'] == meter_statistics_production['measurementType']][0]

        # Is the production meter responding?
        if production_statistics_production_eim['activeCount'] > 0:
            # Production statistics.
            eim_production_w_now = production_statistics_production_eim['wNow']
            eim_production_wh_today = production_statistics_production_eim['whToday']
            eim_production_wh_last_seven_days = production_statistics_production_eim.get('whLastSevenDays')

    # The Consumption meters can be not present (not Gateway Metered) or individually turned off
    # (and they require a working CT clamp).
    eim_consumption_w_now = None
    eim_consumption_wh_today = None

    meter_statistics_consumption = [meter_status for meter_status in meters_status if meter_status['measurementType'] == 'net-consumption' or meter_status['measurementType'] == 'total-consumption'][0]
    if meter_statistics_consumption['state'] == 'enabled':
        # Get the Consumption section for the right meter of the Production Statistics JSON.
        production_statistics_consumption_eim = [production_statistic for production_statistic in production_statistics['consumption'] if production_statistic['type'] == 'eim' and production_statistic['measurementType'] == meter_statistics_consumption['measurementType']][0]

        # Is the consumption meter responding?
        if production_statistics_consumption_eim['activeCount'] > 0:
            # Consumption statistics.
            eim_consumption_w_now = round(production_statistics_consumption_eim['wNow'])
            production_statistics_consumption_eim['wNow'] = eim_consumption_w_now
            eim_consumption_wh_today = production_statistics_consumption_eim['whToday']

    mqtt.publish_obj("meters", meters_status)

    # We support Unicode and ANSI modes of running this application.
    # Check the Windows® console can display UTF-8 characters.
    if sys.platform != 'win32' or (sys.version_info.major >= 3 and sys.version_info.minor >= 6) or locale.getpreferredencoding() == 'cp65001':
        string_names = {'Production': '⚡', 'Microinverter': '⬛', 'Meter': '✏️', 'Lifetime': '⛅', 'Details': '⏰ '}
    else:
        string_names = {'Production': 'Production:', 'Microinverter': '-', 'Meter': 'Meter:', 'Lifetime': 'Lifetime:', 'Details': ''}

    # Get the Inverters section of the Production Statistics JSON.
    production_statistics_inverters = [production_statistic for production_statistic in production_statistics['production'] if production_statistic['type'] == 'inverters'][0]

    # Generate the status (with emojis if runtime is utf-8 capable).
    status  = f'\n{string_names["Production"]} Inverters {get_human_readable_power(production_statistics_inverters["wNow"])} ({production_statistics_inverters["activeCount"]} Inverters)'

    # Used to calculate the microinverter automatic polling interval
    # (gateway polls microinverters automatically every 5 minutes).
    latest_inverter_reported = None

    # Get Inverter(s) status.
    inverters = gateway.api_call('/api/v1/production/inverters')

    # Get panel by panel status.
    for inverter in inverters:

        # We convert the last report date timestamp to a datetime.
        ts = inverter["lastReportDate"]
        inverter_last_reported = datetime.datetime.fromtimestamp(ts)
        inverter["lastReportDateStr"] = f'{inverter_last_reported}'
        inverter["lastReportSecsAgo"] = now-ts
        
        # Add the status of this microinverter to our status string.
        status += f'\n  {string_names["Microinverter"]} {inverter["lastReportWatts"]} W (Serial: {inverter["serialNumber"]}, Last Seen: {inverter_last_reported})'

        # Used to calculate the microinverter polling interval
        # (gateway polls microinverters every 5 minutes).
        if not latest_inverter_reported or latest_inverter_reported < inverter_last_reported:
            latest_inverter_reported = inverter_last_reported

    # This will always be present (even without a production meter).
    status += f'\n{string_names["Lifetime"]} Total Generated {get_human_readable_power(production_statistics_inverters["whLifetime"], True)}'

    mqtt.publish_obj("inverters", inverters)

    # This requires a configured Production meter.
    if eim_production_w_now is not None:

        # The current Production meter reading can read < 0 if energy (often a trace amount) is
        # actually flowing the other way from the grid.
        status += f'\n\n{string_names["Meter"]} Current Production {get_human_readable_power(max(0, eim_production_w_now)).rjust(9, " ")}'

        # The production meter needs to have run for at least a day for this to be non-zero.
        if eim_production_wh_today:
            status += f' ({get_human_readable_power(eim_production_wh_today, True)} Today'

            # The production meter has to have run for at least 7 days for this to be non-zero.
            if eim_production_wh_last_seven_days:
                status += f' / {get_human_readable_power(eim_production_wh_last_seven_days, True)} Last 7 Days'

            status += ')'

    # This requires a configured Consumption meter.
    if eim_consumption_w_now:
        status += f'\n{string_names["Meter"]} Current Consumption {get_human_readable_power(eim_consumption_w_now).rjust(8, " ")}'

        # The consumption meter needs to have run for at least a day for this to be non-zero.
        if eim_consumption_wh_today:
            status += f' ({get_human_readable_power(eim_consumption_wh_today, True)} today)'

    # This was when the poll of all the microinverters had completed.
    inverters_reading_time = production_statistics_inverters['readingTime']

    # Microinverters do not power up in very low light.
    if inverters_reading_time != 0:
        # Microinverters are only automatically polled by the gateway every 5 minutes
        # (and they do not respond in very low light).
        next_refresh_time = datetime.datetime.fromtimestamp(inverters_reading_time) + datetime.timedelta(minutes=5)

        # Print when the next update will be available.
        status += f'\n\n{string_names["Details"]}Data Will Next Be Refreshed At {next_refresh_time.time()}'
    else:
        # Print when the last microinverter reported back to the gateway.
        status += f'\n\n{string_names["Details"]}The Last Microinverter Reported At {latest_inverter_reported}'

    # Output to the console.
    # print(chr(27) + "[2J")
    print(status)

def main():
    """
    Main function for collecting and displaying Enphase® Gateway and inverter status.

    This function loads credentials from a JSON file, initializes a secure session with the Enphase
    Gateway API, retrieves production and meter statistics, and displays the status information to
    the console.

    Args:
        None

    Returns:
        None
    """

    # Load credentials.
    with open('configuration/credentials.json', mode='r', encoding='utf-8') as json_file:
        credentials = json.load(json_file)
        # allow environment variables of same to override config file
        for k in credentials:
            e=os.getenv(k)
            if e:
                credentials[k]=e
                print(f"Env:  {k}={e}")
            else:
                print(f"Cred: {k}={credentials[k]}")

    # and "local" file overrides that also
    try:
        if os.path.exists('configuration/local_credentials.json'):
            with open('configuration/local_credentials.json', mode='r', encoding='utf-8') as local_file:
                local_credentials = json.load(local_file)
                for k in local_credentials:
                    e=os.getenv(k)
                    if e:
                        credentials[k]=e
                        print(f"Env:  {k}={e}")
                    else:
                        credentials[k]=local_credentials[k]
                        print(f"Local: {k}={credentials[k]}")
    except:
        pass

    # mqtt client and publish credentials/config
    print("Starting mqtt")
    mqtt.start(credentials)
    mqtt.publish_time("poll/initialized")
    mqtt.publish_obj("poll/credentials", credentials)

    while (True):
        # every minute force mqtt refresh (otherwise only changed values)
        for x in range(60):
            st = time.time()
            if x == 0:
                mqtt.clear_cache()
                mqtt.publish_time("poll/refresh")
            else:
                mqtt.publish_time("poll/process")
            process(credentials)
            secs = time.time()-st
            mqtt.publish("poll/secs", secs)
            print(f"that took {secs}s")
            if (secs < 1):
                time.sleep(1-secs)        

# Launch the main method if invoked directly.
if __name__ == '__main__':
    main()
    
