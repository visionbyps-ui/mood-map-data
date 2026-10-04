#!/usr/bin/env python3
"""
fetch_news_data.py — Full mood-index computer for the Global Mood Map.

WHY THIS EXISTS:
Earlier versions of this script only pre-fetched news/disaster data, leaving
weather and the final score calculation to run live in the browser on every
page load. This version computes the ENTIRE composite score server-side —
baseline, weather, news tone, and disasters — so the page just reads one
small JSON file and renders instantly, with zero live API calls needed at
load time. That's what makes the page fast and snappy.

Runs on GitHub's own servers via the included Actions workflow (not your
home network), a few times a day — see .github/workflows/fetch-data.yml.

OUTPUT: mood-index-data.json — one record per tracked country with its
final score and full breakdown, ready for the page to display as-is.
"""

import json
import math
import threading
import time
import urllib.request
import urllib.parse
import urllib.error
import re
from html.parser import HTMLParser
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

OUTPUT_FILE = "mood-index-data.json"
REQUEST_TIMEOUT_SEC = 15          # weather/USGS/GDACS — these are reliable, keep generous
GDELT_TIMEOUT_SEC = 10            # GDELT specifically can hang — fail faster so one slow
                                   # country doesn't eat a disproportionate amount of runtime
COUNTRY_WORKERS = 8               # countries processed in parallel
GDELT_MAX_CONCURRENT = 1          # GDELT's real rate limit is stricter than it looks — even 3
                                   # concurrent requests triggered widespread 429s in testing.
                                   # Fully serialized is slower but actually gets real data back.
gdelt_semaphore = threading.Semaphore(GDELT_MAX_CONCURRENT)
GDELT_RETRY_DELAYS = [2, 5, 10]    # seconds to wait before each retry on a 429, with backoff
GDELT_MIN_INTERVAL_SEC = 1.0       # minimum pacing between ANY two GDELT requests, even on
                                    # success — the 429s seen in testing suggest GDELT's limit
                                    # is about request rate, not just concurrency

COUNTRIES = [{"name": "United States", "fips": "US", "lat": 38.9, "lon": -77.0}, {"name": "Canada", "fips": "CA", "lat": 45.4, "lon": -75.7}, {"name": "Mexico", "fips": "MX", "lat": 19.4, "lon": -99.1}, {"name": "Guatemala", "fips": "GT", "lat": 14.63, "lon": -90.5}, {"name": "Honduras", "fips": "HO", "lat": 14.1, "lon": -87.2}, {"name": "El Salvador", "fips": "ES", "lat": 13.7, "lon": -89.2}, {"name": "Nicaragua", "fips": "NU", "lat": 12.1, "lon": -86.25}, {"name": "Costa Rica", "fips": "CS", "lat": 9.93, "lon": -84.08}, {"name": "Panama", "fips": "PM", "lat": 8.98, "lon": -79.52}, {"name": "Cuba", "fips": "CU", "lat": 23.13, "lon": -82.38}, {"name": "Jamaica", "fips": "JM", "lat": 18.0, "lon": -76.8}, {"name": "Dominican Rep.", "fips": "DR", "lat": 18.48, "lon": -69.9}, {"name": "Trinidad and Tobago", "fips": "TD", "lat": 10.65, "lon": -61.5}, {"name": "Brazil", "fips": "BR", "lat": -15.8, "lon": -47.9}, {"name": "Argentina", "fips": "AR", "lat": -34.6, "lon": -58.4}, {"name": "Chile", "fips": "CI", "lat": -33.4, "lon": -70.6}, {"name": "Colombia", "fips": "CO", "lat": 4.7, "lon": -74.1}, {"name": "Peru", "fips": "PE", "lat": -12.0, "lon": -77.0}, {"name": "Uruguay", "fips": "UY", "lat": -34.9, "lon": -56.16}, {"name": "Paraguay", "fips": "PA", "lat": -25.3, "lon": -57.63}, {"name": "Bolivia", "fips": "BL", "lat": -16.5, "lon": -68.15}, {"name": "Ecuador", "fips": "EC", "lat": -0.23, "lon": -78.52}, {"name": "Venezuela", "fips": "VE", "lat": 10.5, "lon": -66.9}, {"name": "Guyana", "fips": "GY", "lat": 6.8, "lon": -58.16}, {"name": "Suriname", "fips": "NS", "lat": 5.87, "lon": -55.17}, {"name": "United Kingdom", "fips": "UK", "lat": 51.5, "lon": -0.1}, {"name": "France", "fips": "FR", "lat": 48.85, "lon": 2.35}, {"name": "Germany", "fips": "GM", "lat": 52.5, "lon": 13.4}, {"name": "Spain", "fips": "SP", "lat": 40.4, "lon": -3.7}, {"name": "Italy", "fips": "IT", "lat": 41.9, "lon": 12.5}, {"name": "Portugal", "fips": "PO", "lat": 38.7, "lon": -9.1}, {"name": "Netherlands", "fips": "NL", "lat": 52.4, "lon": 4.9}, {"name": "Belgium", "fips": "BE", "lat": 50.85, "lon": 4.35}, {"name": "Switzerland", "fips": "SZ", "lat": 46.95, "lon": 7.45}, {"name": "Austria", "fips": "AU", "lat": 48.2, "lon": 16.37}, {"name": "Sweden", "fips": "SW", "lat": 59.3, "lon": 18.07}, {"name": "Norway", "fips": "NO", "lat": 59.9, "lon": 10.75}, {"name": "Denmark", "fips": "DA", "lat": 55.68, "lon": 12.57}, {"name": "Finland", "fips": "FI", "lat": 60.17, "lon": 24.94}, {"name": "Iceland", "fips": "IC", "lat": 64.15, "lon": -21.94}, {"name": "Poland", "fips": "PL", "lat": 52.23, "lon": 21.0}, {"name": "Ukraine", "fips": "UP", "lat": 50.45, "lon": 30.52}, {"name": "Russia", "fips": "RS", "lat": 55.75, "lon": 37.6}, {"name": "Greece", "fips": "GR", "lat": 37.98, "lon": 23.73}, {"name": "Turkey", "fips": "TU", "lat": 39.9, "lon": 32.85}, {"name": "Ireland", "fips": "EI", "lat": 53.35, "lon": -6.26}, {"name": "Czechia", "fips": "EZ", "lat": 50.08, "lon": 14.44}, {"name": "Slovakia", "fips": "LO", "lat": 48.15, "lon": 17.1}, {"name": "Hungary", "fips": "HU", "lat": 47.5, "lon": 19.05}, {"name": "Romania", "fips": "RO", "lat": 44.43, "lon": 26.1}, {"name": "Bulgaria", "fips": "BU", "lat": 42.7, "lon": 23.32}, {"name": "Serbia", "fips": "RI", "lat": 44.8, "lon": 20.47}, {"name": "Croatia", "fips": "HR", "lat": 45.8, "lon": 15.98}, {"name": "Slovenia", "fips": "SI", "lat": 46.05, "lon": 14.5}, {"name": "Bosnia and Herz.", "fips": "BK", "lat": 43.85, "lon": 18.35}, {"name": "Albania", "fips": "AL", "lat": 41.33, "lon": 19.82}, {"name": "North Macedonia", "fips": "MK", "lat": 42.0, "lon": 21.43}, {"name": "Lithuania", "fips": "LH", "lat": 54.68, "lon": 25.28}, {"name": "Latvia", "fips": "LG", "lat": 56.95, "lon": 24.1}, {"name": "Estonia", "fips": "EN", "lat": 59.44, "lon": 24.75}, {"name": "Belarus", "fips": "BO", "lat": 53.9, "lon": 27.57}, {"name": "Moldova", "fips": "MD", "lat": 47.02, "lon": 28.86}, {"name": "Cyprus", "fips": "CY", "lat": 35.17, "lon": 33.36}, {"name": "Luxembourg", "fips": "LU", "lat": 49.6, "lon": 6.13}, {"name": "Egypt", "fips": "EG", "lat": 30.04, "lon": 31.24}, {"name": "Nigeria", "fips": "NI", "lat": 9.08, "lon": 7.4}, {"name": "South Africa", "fips": "SF", "lat": -25.75, "lon": 28.2}, {"name": "Kenya", "fips": "KE", "lat": -1.3, "lon": 36.8}, {"name": "Morocco", "fips": "MO", "lat": 34.0, "lon": -6.8}, {"name": "Algeria", "fips": "AG", "lat": 36.75, "lon": 3.05}, {"name": "Tunisia", "fips": "TS", "lat": 36.8, "lon": 10.18}, {"name": "Libya", "fips": "LY", "lat": 32.87, "lon": 13.19}, {"name": "Ethiopia", "fips": "ET", "lat": 9.03, "lon": 38.74}, {"name": "Ghana", "fips": "GH", "lat": 5.6, "lon": -0.2}, {"name": "Côte d'Ivoire", "fips": "IV", "lat": 6.85, "lon": -5.3}, {"name": "Senegal", "fips": "SG", "lat": 14.7, "lon": -17.45}, {"name": "Cameroon", "fips": "CM", "lat": 3.85, "lon": 11.5}, {"name": "Angola", "fips": "AO", "lat": -8.83, "lon": 13.23}, {"name": "Zambia", "fips": "ZA", "lat": -15.4, "lon": 28.3}, {"name": "Zimbabwe", "fips": "ZI", "lat": -17.83, "lon": 31.05}, {"name": "Mozambique", "fips": "MZ", "lat": -25.97, "lon": 32.58}, {"name": "Namibia", "fips": "WA", "lat": -22.57, "lon": 17.08}, {"name": "Botswana", "fips": "BC", "lat": -24.65, "lon": 25.9}, {"name": "Uganda", "fips": "UG", "lat": 0.31, "lon": 32.58}, {"name": "Tanzania", "fips": "TZ", "lat": -6.8, "lon": 39.28}, {"name": "Saudi Arabia", "fips": "SA", "lat": 24.7, "lon": 46.7}, {"name": "United Arab Emirates", "fips": "AE", "lat": 24.47, "lon": 54.37}, {"name": "Israel", "fips": "IS", "lat": 31.77, "lon": 35.2}, {"name": "Iran", "fips": "IR", "lat": 35.7, "lon": 51.4}, {"name": "Iraq", "fips": "IZ", "lat": 33.32, "lon": 44.36}, {"name": "Jordan", "fips": "JO", "lat": 31.95, "lon": 35.93}, {"name": "Lebanon", "fips": "LE", "lat": 33.89, "lon": 35.5}, {"name": "Syria", "fips": "SY", "lat": 33.5, "lon": 36.3}, {"name": "Yemen", "fips": "YM", "lat": 15.35, "lon": 44.2}, {"name": "Oman", "fips": "MU", "lat": 23.6, "lon": 58.4}, {"name": "Qatar", "fips": "QA", "lat": 25.29, "lon": 51.53}, {"name": "Kuwait", "fips": "KU", "lat": 29.37, "lon": 47.98}, {"name": "Afghanistan", "fips": "AF", "lat": 34.53, "lon": 69.17}, {"name": "India", "fips": "IN", "lat": 28.6, "lon": 77.2}, {"name": "Pakistan", "fips": "PK", "lat": 33.7, "lon": 73.1}, {"name": "Bangladesh", "fips": "BG", "lat": 23.8, "lon": 90.4}, {"name": "Sri Lanka", "fips": "CE", "lat": 6.93, "lon": 79.85}, {"name": "Nepal", "fips": "NP", "lat": 27.7, "lon": 85.3}, {"name": "Myanmar", "fips": "BM", "lat": 19.75, "lon": 96.1}, {"name": "China", "fips": "CH", "lat": 39.9, "lon": 116.4}, {"name": "Mongolia", "fips": "MG", "lat": 47.92, "lon": 106.92}, {"name": "Japan", "fips": "JA", "lat": 35.68, "lon": 139.76}, {"name": "South Korea", "fips": "KS", "lat": 37.57, "lon": 126.98}, {"name": "North Korea", "fips": "KN", "lat": 39.02, "lon": 125.75}, {"name": "Taiwan", "fips": "TW", "lat": 25.03, "lon": 121.56}, {"name": "Indonesia", "fips": "ID", "lat": -6.2, "lon": 106.85}, {"name": "Thailand", "fips": "TH", "lat": 13.75, "lon": 100.5}, {"name": "Vietnam", "fips": "VM", "lat": 21.03, "lon": 105.85}, {"name": "Cambodia", "fips": "CB", "lat": 11.55, "lon": 104.92}, {"name": "Laos", "fips": "LA", "lat": 17.97, "lon": 102.6}, {"name": "Philippines", "fips": "RP", "lat": 14.6, "lon": 121.0}, {"name": "Malaysia", "fips": "MY", "lat": 3.14, "lon": 101.7}, {"name": "Singapore", "fips": "SN", "lat": 1.35, "lon": 103.82}, {"name": "Australia", "fips": "AS", "lat": -35.28, "lon": 149.13}, {"name": "New Zealand", "fips": "NZ", "lat": -41.29, "lon": 174.78}, {"name": "Papua New Guinea", "fips": "PP", "lat": -9.48, "lon": 147.15}, {"name": "Kazakhstan", "fips": "KZ", "lat": 51.17, "lon": 71.43}, {"name": "Benin", "fips": "BN", "lat": 6.5, "lon": 2.6}, {"name": "Burkina Faso", "fips": "UV", "lat": 12.37, "lon": -1.52}, {"name": "Burundi", "fips": "BY", "lat": -3.43, "lon": 29.93}, {"name": "Cabo Verde", "fips": "CV", "lat": 14.93, "lon": -23.51}, {"name": "Central African Republic", "fips": "CT", "lat": 4.37, "lon": 18.56}, {"name": "Chad", "fips": "CD", "lat": 12.13, "lon": 15.06}, {"name": "Comoros", "fips": "CN", "lat": -11.7, "lon": 43.26}, {"name": "Republic of the Congo", "fips": "CF", "lat": -4.26, "lon": 15.28}, {"name": "Democratic Republic of the Congo", "fips": "CG", "lat": -4.44, "lon": 15.27}, {"name": "Djibouti", "fips": "DJ", "lat": 11.59, "lon": 43.15}, {"name": "Equatorial Guinea", "fips": "EK", "lat": 3.75, "lon": 8.78}, {"name": "Eritrea", "fips": "ER", "lat": 15.32, "lon": 38.93}, {"name": "Eswatini", "fips": "WZ", "lat": -26.32, "lon": 31.13}, {"name": "Gabon", "fips": "GB", "lat": 0.42, "lon": 9.45}, {"name": "Gambia", "fips": "GA", "lat": 13.45, "lon": -16.58}, {"name": "Guinea", "fips": "GV", "lat": 9.51, "lon": -13.71}, {"name": "Guinea-Bissau", "fips": "PU", "lat": 11.86, "lon": -15.6}, {"name": "Lesotho", "fips": "LT", "lat": -29.31, "lon": 27.48}, {"name": "Liberia", "fips": "LI", "lat": 6.3, "lon": -10.8}, {"name": "Madagascar", "fips": "MA", "lat": -18.88, "lon": 47.51}, {"name": "Malawi", "fips": "MI", "lat": -13.96, "lon": 33.79}, {"name": "Mali", "fips": "ML", "lat": 12.65, "lon": -8.0}, {"name": "Mauritania", "fips": "MR", "lat": 18.09, "lon": -15.98}, {"name": "Mauritius", "fips": "MP", "lat": -20.16, "lon": 57.5}, {"name": "Niger", "fips": "NG", "lat": 13.51, "lon": 2.11}, {"name": "Rwanda", "fips": "RW", "lat": -1.94, "lon": 30.06}, {"name": "Sao Tome and Principe", "fips": "TP", "lat": 0.33, "lon": 6.73}, {"name": "Seychelles", "fips": "SE", "lat": -4.62, "lon": 55.45}, {"name": "Sierra Leone", "fips": "SL", "lat": 8.48, "lon": -13.23}, {"name": "Somalia", "fips": "SO", "lat": 2.04, "lon": 45.34}, {"name": "South Sudan", "fips": "OD", "lat": 4.85, "lon": 31.58}, {"name": "Sudan", "fips": "SU", "lat": 15.5, "lon": 32.56}, {"name": "Togo", "fips": "TO", "lat": 6.13, "lon": 1.22}]

WHR_BASELINE = {"Finland": 7.74, "Denmark": 7.58, "Iceland": 7.53, "Sweden": 7.34, "Israel": 7.34, "Netherlands": 7.31, "Norway": 7.3, "Luxembourg": 7.12, "Switzerland": 7.06, "Australia": 7.06, "New Zealand": 7.03, "Costa Rica": 6.94, "Austria": 6.96, "Canada": 6.9, "Ireland": 6.83, "Belgium": 6.86, "United Kingdom": 6.72, "Germany": 6.72, "United States": 6.72, "Mexico": 6.9, "United Arab Emirates": 6.73, "France": 6.66, "Czechia": 6.85, "Slovenia": 6.61, "Taiwan": 6.53, "Singapore": 6.52, "Kuwait": 6.58, "Saudi Arabia": 6.49, "El Salvador": 6.49, "Spain": 6.42, "Italy": 6.41, "Uruguay": 6.68, "Panama": 6.26, "Guatemala": 6.19, "Nicaragua": 6.14, "Chile": 6.38, "Vietnam": 6.05, "Kazakhstan": 6.06, "Romania": 6.36, "Serbia": 6.3, "Poland": 6.32, "Brazil": 6.29, "Malaysia": 6.1, "Argentina": 6.24, "Thailand": 5.98, "Qatar": 6.6, "Oman": 6.0, "China": 5.97, "Japan": 6.13, "South Korea": 5.9, "Philippines": 5.9, "Indonesia": 5.6, "Bulgaria": 5.63, "Greece": 5.72, "Russia": 5.66, "Bolivia": 5.65, "Paraguay": 5.87, "Honduras": 5.84, "Jamaica": 5.89, "Dominican Rep.": 5.8, "Trinidad and Tobago": 5.9, "Colombia": 5.63, "Peru": 5.55, "Ecuador": 5.55, "Namibia": 5.2, "Algeria": 5.2, "Morocco": 5.06, "Ghana": 5.03, "Côte d'Ivoire": 5.29, "Nepal": 5.1, "Botswana": 4.5, "Venezuela": 5.17, "Libya": 5.4, "Turkey": 5.24, "Jordan": 4.9, "Cameroon": 4.6, "Senegal": 4.9, "Iran": 4.7, "Iraq": 4.6, "Tunisia": 4.7, "Myanmar": 4.4, "Cambodia": 4.4, "Laos": 4.5, "Pakistan": 4.65, "Kenya": 4.6, "Nigeria": 4.85, "Uganda": 4.3, "Egypt": 4.28, "South Africa": 4.92, "India": 4.05, "Sri Lanka": 3.9, "Angola": 4.36, "Ethiopia": 4.0, "Zambia": 4.03, "Bangladesh": 3.85, "Tanzania": 3.7, "Mozambique": 4.0, "Syria": 3.5, "Yemen": 3.6, "Zimbabwe": 3.3, "Lebanon": 3.19, "Afghanistan": 1.72, "Benin": 4.4, "Burkina Faso": 4.38, "Burundi": 3.55, "Cabo Verde": 5.87, "Central African Republic": 3.48, "Chad": 4.4, "Comoros": 4.28, "Republic of the Congo": 4.8, "Democratic Republic of the Congo": 4.32, "Djibouti": 4.5, "Equatorial Guinea": 5.0, "Eritrea": 4.5, "Eswatini": 4.4, "Gabon": 5.4, "Gambia": 4.64, "Guinea": 4.63, "Guinea-Bissau": 4.6, "Lesotho": 3.65, "Liberia": 4.63, "Madagascar": 4.0, "Malawi": 3.75, "Mali": 4.4, "Mauritania": 5.19, "Mauritius": 6.0, "Niger": 4.35, "Rwanda": 3.35, "Sao Tome and Principe": 4.8, "Seychelles": 6.1, "Sierra Leone": 4.5, "Somalia": 4.0, "South Sudan": 2.8, "Sudan": 3.8, "Togo": 4.55}

WEATHER_CODE_MAP = {
    0: ("Clear sky", 0.85), 1: ("Mainly clear", 0.78), 2: ("Partly cloudy", 0.62), 3: ("Overcast", 0.45),
    45: ("Fog", 0.4), 48: ("Rime fog", 0.38),
    51: ("Light drizzle", 0.5), 53: ("Drizzle", 0.45), 55: ("Dense drizzle", 0.4),
    61: ("Light rain", 0.42), 63: ("Rain", 0.35), 65: ("Heavy rain", 0.22),
    71: ("Light snow", 0.5), 73: ("Snow", 0.42), 75: ("Heavy snow", 0.3),
    80: ("Rain showers", 0.4), 81: ("Rain showers", 0.35), 82: ("Violent showers", 0.18),
    95: ("Thunderstorm", 0.2), 96: ("Thunderstorm w/ hail", 0.15), 99: ("Severe thunderstorm", 0.12),
}
GDACS_HAZARD_LABELS = {"TC": "Tropical cyclone", "FL": "Flood", "VO": "Volcanic activity", "WF": "Wildfire"}

# ---------------------------------------------------------------
# LONGEVITY — informational only, not part of the composite score.
#
# Life expectancy comes live from the World Bank API (free, no key), matched
# by ISO3 country code. Taiwan isn't published by the World Bank, so it will
# show as unavailable.
#
# Centenarian (100+) counts are static: official national statistics-office
# figures compiled in Wikipedia's "Centenarian" article (the year of each
# figure varies, 2011-2026, and is shown on the page), with Japan's taken from
# its Ministry of Health, Labour and Welfare's Sept 2026 release. Only ~47
# countries publish a usable national count; the rest are left out rather than
# estimated. Counts can also be inflated by record-keeping errors, so treat
# them as approximate. Counts per single year of age beyond 100 aren't
# available in any open dataset used here, so they are not included.
# ---------------------------------------------------------------
ISO3 = {"United States":"USA","Canada":"CAN","Mexico":"MEX","Guatemala":"GTM","Honduras":"HND","El Salvador":"SLV","Nicaragua":"NIC","Costa Rica":"CRI","Panama":"PAN","Cuba":"CUB","Jamaica":"JAM","Dominican Rep.":"DOM","Trinidad and Tobago":"TTO","Brazil":"BRA","Argentina":"ARG","Chile":"CHL","Colombia":"COL","Peru":"PER","Uruguay":"URY","Paraguay":"PRY","Bolivia":"BOL","Ecuador":"ECU","Venezuela":"VEN","Guyana":"GUY","Suriname":"SUR","United Kingdom":"GBR","France":"FRA","Germany":"DEU","Spain":"ESP","Italy":"ITA","Portugal":"PRT","Netherlands":"NLD","Belgium":"BEL","Switzerland":"CHE","Austria":"AUT","Sweden":"SWE","Norway":"NOR","Denmark":"DNK","Finland":"FIN","Iceland":"ISL","Poland":"POL","Ukraine":"UKR","Russia":"RUS","Greece":"GRC","Turkey":"TUR","Ireland":"IRL","Czechia":"CZE","Slovakia":"SVK","Hungary":"HUN","Romania":"ROU","Bulgaria":"BGR","Serbia":"SRB","Croatia":"HRV","Slovenia":"SVN","Bosnia and Herz.":"BIH","Albania":"ALB","North Macedonia":"MKD","Lithuania":"LTU","Latvia":"LVA","Estonia":"EST","Belarus":"BLR","Moldova":"MDA","Cyprus":"CYP","Luxembourg":"LUX","Egypt":"EGY","Nigeria":"NGA","South Africa":"ZAF","Kenya":"KEN","Morocco":"MAR","Algeria":"DZA","Tunisia":"TUN","Libya":"LBY","Ethiopia":"ETH","Ghana":"GHA","Côte d'Ivoire":"CIV","Senegal":"SEN","Cameroon":"CMR","Angola":"AGO","Zambia":"ZMB","Zimbabwe":"ZWE","Mozambique":"MOZ","Namibia":"NAM","Botswana":"BWA","Uganda":"UGA","Tanzania":"TZA","Saudi Arabia":"SAU","United Arab Emirates":"ARE","Israel":"ISR","Iran":"IRN","Iraq":"IRQ","Jordan":"JOR","Lebanon":"LBN","Syria":"SYR","Yemen":"YEM","Oman":"OMN","Qatar":"QAT","Kuwait":"KWT","Afghanistan":"AFG","India":"IND","Pakistan":"PAK","Bangladesh":"BGD","Sri Lanka":"LKA","Nepal":"NPL","Myanmar":"MMR","China":"CHN","Mongolia":"MNG","Japan":"JPN","South Korea":"KOR","North Korea":"PRK","Taiwan":"TWN","Indonesia":"IDN","Thailand":"THA","Vietnam":"VNM","Cambodia":"KHM","Laos":"LAO","Philippines":"PHL","Malaysia":"MYS","Singapore":"SGP","Australia":"AUS","New Zealand":"NZL","Papua New Guinea":"PNG","Kazakhstan":"KAZ","Benin":"BEN","Burkina Faso":"BFA","Burundi":"BDI","Cabo Verde":"CPV","Central African Republic":"CAF","Chad":"TCD","Comoros":"COM","Republic of the Congo":"COG","Democratic Republic of the Congo":"COD","Djibouti":"DJI","Equatorial Guinea":"GNQ","Eritrea":"ERI","Eswatini":"SWZ","Gabon":"GAB","Gambia":"GMB","Guinea":"GIN","Guinea-Bissau":"GNB","Lesotho":"LSO","Liberia":"LBR","Madagascar":"MDG","Malawi":"MWI","Mali":"MLI","Mauritania":"MRT","Mauritius":"MUS","Niger":"NER","Rwanda":"RWA","Sao Tome and Principe":"STP","Seychelles":"SYC","Sierra Leone":"SLE","Somalia":"SOM","South Sudan":"SSD","Sudan":"SDN","Togo":"TGO"}

# name: (centenarian count, year of the figure)
CENTENARIANS = {
    "Argentina": (6043, 2025), "Australia": (7345, 2025), "Austria": (1841, 2026), "Belgium": (3172, 2025),
    "Brazil": (37814, 2022), "Bulgaria": (353, 2022), "Cambodia": (3143, 2019), "Canada": (12281, 2025),
    "China": (54166, 2013), "Colombia": (19400, 2023), "Croatia": (944, 2023), "Czechia": (977, 2024),
    "Denmark": (1224, 2025), "Estonia": (255, 2026), "Finland": (1153, 2023), "France": (37000, 2025),
    "Germany": (17901, 2024), "Hungary": (906, 2023), "Iceland": (47, 2023), "India": (27000, 2015),
    "Ireland": (956, 2023), "Israel": (3328, 2022), "Italy": (24710, 2026), "Japan": (107677, 2026),
    "Malaysia": (2296, 2024), "Mexico": (18295, 2020), "Netherlands": (2583, 2025), "New Zealand": (1078, 2024),
    "Norway": (1382, 2026), "Peru": (2707, 2013), "Poland": (7387, 2023), "Portugal": (4143, 2025),
    "Romania": (3713, 2026), "Russia": (22600, 2020), "Singapore": (1500, 2020), "Slovenia": (388, 2025),
    "Slovakia": (401, 2021), "South Africa": (22525, 2023), "South Korea": (8891, 2025), "Spain": (19573, 2022),
    "Sweden": (2961, 2024), "Switzerland": (1948, 2023), "Thailand": (45561, 2024), "Turkey": (8290, 2025),
    "United Kingdom": (16600, 2024), "United States": (119182, 2025), "Uruguay": (519, 2011),
}

WB_LIFE_EXPECTANCY_INDICATORS = {
    "total": "SP.DYN.LE00.IN", "male": "SP.DYN.LE00.MA.IN", "female": "SP.DYN.LE00.FE.IN",
}


def fetch_life_expectancy():
    """World Bank life expectancy at birth, most recent non-empty value per
    country. Returns {iso3: {"total":..., "male":..., "female":..., "year":...}}.
    If the request fails, returns whatever was gathered — the page simply shows
    life expectancy as unavailable for those countries."""
    result = {}
    for key, indicator in WB_LIFE_EXPECTANCY_INDICATORS.items():
        url = (f"https://api.worldbank.org/v2/country/all/indicator/{indicator}"
               f"?format=json&per_page=1000&mrnev=1")
        try:
            data = fetch_json(url, timeout=30)
            rows = data[1] if isinstance(data, list) and len(data) > 1 and data[1] else []
            for row in rows:
                iso3, value = row.get("countryiso3code"), row.get("value")
                if not iso3 or value is None:
                    continue
                entry = result.setdefault(iso3, {})
                entry[key] = round(float(value), 1)
                if key == "total":
                    entry["year"] = row.get("date")
            print(f"  ok — life expectancy ({key}): {len(rows)} rows")
        except Exception as e:
            print(f"  ! World Bank {key} life expectancy fetch failed: {e}")
    return result


# ---------------------------------------------------------------
# OLDEST LIVING PERSON per country — informational, not part of the score.
#
# Fetched live on every run from the Gerontology Research Group's ranking of
# validated living supercentenarians (110+), because people this old die often
# and a static copy would go stale within weeks. Each person is assigned to
# their country of last residence and the earliest birth date per country is
# kept. Only the birth date is stored (the page computes the current age from
# it) — no names. Countries with no validated person simply have no entry.
#
# The GRG list can lag other validators. SUPPLEMENTAL_OLDEST holds the few
# cases found where Wikipedia's per-country lists show an older validated
# person who is missing from the GRG list; each is only used when it is older
# than the GRG entry, and it is labelled with its "as of" date.
# ---------------------------------------------------------------
GRG_URL = "https://www.grg-supercentenarians.org/world-supercentenarian-rankings-list/"
GRG_NAME_ALIASES = {
    "UK": "United Kingdom", "USA": "United States", "Dominican Republic": "Dominican Rep.",
    "Czech Republic": "Czechia", "Bosnia and Herzegovina": "Bosnia and Herz.",
    "Ivory Coast": "Côte d'Ivoire", "Cote d'Ivoire": "Côte d'Ivoire", "Cape Verde": "Cabo Verde",
}
SUPPLEMENTAL_OLDEST = {
    "Brazil": {"born": "1911-06-21", "asOf": "2026-09-27",
               "source": "Wikipedia: List of the verified oldest people",
               "url": "https://en.wikipedia.org/wiki/List_of_the_verified_oldest_people"},
    "Spain": {"born": "1913-07-29", "asOf": "2026-09-27",
              "source": "Wikipedia: List of Spanish supercentenarians",
              "url": "https://en.wikipedia.org/wiki/List_of_Spanish_supercentenarians"},
}


def fetch_text(url, timeout=REQUEST_TIMEOUT_SEC):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; GlobalMoodMapCollector/1.0)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


class _TableRows(HTMLParser):
    """Collects the text of every cell of every table row, ignoring markup."""
    def __init__(self):
        super().__init__()
        self.rows, self._row, self._cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._row is not None and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None


def parse_grg_oldest(html_text, known_names, today=None):
    """Return {country: earliest ISO birth date} from the GRG table HTML."""
    today = today or datetime.now(timezone.utc).date()
    parser = _TableRows()
    parser.feed(html_text)
    oldest = {}
    for cells in parser.rows:
        if len(cells) < 8:
            continue
        born, residence = cells[2], cells[7]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", born):
            continue
        try:
            born_date = datetime.strptime(born, "%Y-%m-%d").date()
        except ValueError:
            continue
        age_years = (today - born_date).days / 365.25
        if not (105 <= age_years <= 125):   # sanity: this is a supercentenarian list
            continue
        country = residence.split(" (")[0].strip()
        country = GRG_NAME_ALIASES.get(country, country)
        if country not in known_names:
            continue
        if country not in oldest or born < oldest[country]:
            oldest[country] = born
    return oldest


def fetch_oldest_living():
    """{country: {"born", "source", "url", ["asOf"]}} — GRG live, plus any
    older supplemental entries. Returns {} if the GRG page can't be read."""
    known = {c["name"] for c in COUNTRIES}
    result = {}
    try:
        grg = parse_grg_oldest(fetch_text(GRG_URL, timeout=30), known)
        for country, born in grg.items():
            result[country] = {"born": born, "source": "Gerontology Research Group", "url": GRG_URL}
        print(f"  ok — GRG list: oldest living person found for {len(grg)} countries")
        if not grg:
            print("  ! GRG page parsed but no rows matched — has the page layout changed?")
    except Exception as e:
        print(f"  ! GRG list fetch failed: {e}")
    for country, entry in SUPPLEMENTAL_OLDEST.items():
        if country not in result or entry["born"] < result[country]["born"]:
            result[country] = dict(entry)
    return result


def longevity_for(name, life_exp, oldest=None):
    le = life_exp.get(ISO3.get(name), {})
    cent = CENTENARIANS.get(name)
    return {
        "lifeExpectancy": le.get("total"),
        "lifeExpectancyMale": le.get("male"),
        "lifeExpectancyFemale": le.get("female"),
        "lifeExpectancyYear": le.get("year"),
        "centenarians": {"count": cent[0], "year": cent[1]} if cent else None,
        "oldestLiving": (oldest or {}).get(name),
    }


def fetch_json(url, timeout=REQUEST_TIMEOUT_SEC):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; GlobalMoodMapCollector/1.0)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def baseline_for(name):
    if name in WHR_BASELINE:
        return {"score": WHR_BASELINE[name], "reported": True}
    return {"score": 5.3, "reported": False}


def fetch_weather(c):
    url = f"https://api.open-meteo.com/v1/forecast?latitude={c['lat']}&longitude={c['lon']}&current_weather=true"
    data = fetch_json(url)
    cw = data["current_weather"]
    temp = cw["temperature"]
    code = cw["weathercode"]
    label, cond_mood = WEATHER_CODE_MAP.get(code, ("Mixed conditions", 0.5))
    if temp < -10: temp_mood = 0.15
    elif temp < 0: temp_mood = 0.3
    elif temp < 10: temp_mood = 0.5
    elif temp < 18: temp_mood = 0.7
    elif temp <= 24: temp_mood = 0.9
    elif temp <= 30: temp_mood = 0.65
    elif temp <= 36: temp_mood = 0.4
    else: temp_mood = 0.2
    mood = cond_mood * 0.6 + temp_mood * 0.4
    return {"label": label, "tempC": round(temp), "mood": mood, "sourceUrl": url}


def fetch_tone(fips, topic_words):
    q = urllib.parse.quote(f"({topic_words}) sourcecountry:{fips}")
    url = f"https://api.gdeltproject.org/api/v2/doc/doc?query={q}&mode=timelinetone&format=json&timespan=3d"
    articles_url = f"https://api.gdeltproject.org/api/v2/doc/doc?query={q}&mode=artlist&format=html&maxrecords=15&timespan=3d"
    # Countries run in parallel (see main()), but this semaphore keeps GDELT
    # requests fully serialized — 3 concurrent was still triggering 429s.
    with gdelt_semaphore:
        attempts = [GDELT_MIN_INTERVAL_SEC] + GDELT_RETRY_DELAYS  # pace every attempt, with backoff on retries
        last_error = None
        for attempt_num, delay in enumerate(attempts):
            if delay:
                time.sleep(delay)
            try:
                data = fetch_json(url, timeout=GDELT_TIMEOUT_SEC)
                series = (data.get("timeline") or [{}])[0].get("data") or []
                if not series:
                    return None
                last = series[-4:]
                avg_tone = sum(p["value"] for p in last) / len(last)
                mood = max(0.0, min(1.0, (avg_tone + 6) / 12))
                return {"tone": avg_tone, "mood": mood, "articlesUrl": articles_url}
            except urllib.error.HTTPError as e:
                last_error = e
                if e.code == 429 and attempt_num < len(attempts) - 1:
                    continue  # retry after backoff
                print(f"      ! tone fetch failed ({topic_words[:20]}...): {e}")
                return None
            except Exception as e:
                last_error = e
                print(f"      ! tone fetch failed ({topic_words[:20]}...): {e}")
                return None
        print(f"      ! tone fetch gave up after retries ({topic_words[:20]}...): {last_error}")
        return None


def fetch_disasters():
    def haversine_km(lat1, lon1, lat2, lon2):
        R = 6371
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
        a = math.sin(dlat/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dlon/2)**2
        return 2 * R * math.asin(math.sqrt(a))

    disaster_by_country = {}
    now_ms = time.time() * 1000

    def add_event(name, severity, event):
        entry = disaster_by_country.setdefault(name, {"severity": 0.0, "events": []})
        entry["severity"] = min(1.0, entry["severity"] + severity * 0.6)
        entry["events"].append(event)

    print("Fetching earthquakes (USGS)...")
    try:
        data = fetch_json("https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_month.geojson")
        for f in data.get("features", []):
            props = f["properties"]
            place = (props.get("place") or "").lower()
            mag = props.get("mag") or 0
            tsunami = props.get("tsunami") == 1
            time_ms = props.get("time") or now_ms
            lon, lat = f["geometry"]["coordinates"][:2]
            days_ago = (now_ms - time_ms) / 86400000
            if days_ago > 30 or days_ago < 0:
                continue
            matched = next((c for c in COUNTRIES if c["name"].lower() in place), None)
            if not matched:
                best, best_dist = None, 700
                for c in COUNTRIES:
                    d = haversine_km(lat, lon, c["lat"], c["lon"])
                    if d < best_dist:
                        best_dist, best = d, c
                matched = best
            if not matched:
                continue
            recency = max(0, 1 - days_ago / 30)
            mag_weight = max(0, min(1, (mag - 4.5) / 3.5))
            severity = mag_weight * (0.55 + recency * 0.45) + (0.25 if tsunami else 0)
            add_event(matched["name"], severity, {
                "kind": "EQ", "label": f"M{mag:.1f} earthquake" + (" (tsunami warning)" if tsunami else ""),
                "place": props.get("place"), "daysAgo": round(days_ago), "url": props.get("url"),
            })
        print(f"  ok — {len(data.get('features', []))} earthquakes processed")
    except Exception as e:
        print(f"  ! USGS fetch failed: {e}")

    print("Fetching storms/floods/volcanoes/wildfires (GDACS)...")
    try:
        from_date = datetime.fromtimestamp(now_ms/1000 - 30*86400, tz=timezone.utc).strftime("%Y-%m-%d")
        to_date = datetime.fromtimestamp(now_ms/1000, tz=timezone.utc).strftime("%Y-%m-%d")
        url = (f"https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"
               f"?eventlist=TC;FL;VO;WF&fromdate={from_date}&todate={to_date}&alertlevel=orange;red")
        data = fetch_json(url, timeout=20)
        count = 0
        for f in data.get("features", []):
            p = f.get("properties", {})
            kind = p.get("eventtype")
            label = GDACS_HAZARD_LABELS.get(kind)
            if not label:
                continue
            country_text = str(p.get("country") or p.get("iso3") or "").lower()
            date_str = (p.get("fromdate") or p.get("todate") or "")[:10]
            from_date_ms = time.mktime(time.strptime(date_str, "%Y-%m-%d")) * 1000 if date_str else now_ms
            days_ago = max(0, (now_ms - from_date_ms) / 86400000)
            if days_ago > 30:
                continue
            matches = [c for c in COUNTRIES if c["name"].lower() in country_text]
            if not matches:
                continue
            alert_weight = {"green": 0.3, "orange": 0.65, "red": 1.0}.get((p.get("alertlevel") or "").lower(), 0.5)
            recency = max(0, 1 - days_ago / 30)
            severity = alert_weight * (0.55 + recency * 0.45)
            for c in matches:
                add_event(c["name"], severity, {
                    "kind": kind, "label": label + (f" ({p['alertlevel']} alert)" if p.get("alertlevel") else ""),
                    "place": p.get("eventname") or p.get("country") or label, "daysAgo": round(days_ago),
                    "url": f"https://www.gdacs.org/report.aspx?eventid={p.get('eventid')}&eventtype={kind}",
                })
                count += 1
        print(f"  ok — {count} hazard events matched")
    except Exception as e:
        print(f"  ! GDACS fetch failed: {e}")

    result = {}
    for name, entry in disaster_by_country.items():
        events = sorted(entry["events"], key=lambda e: e["daysAgo"])[:4]
        result[name] = {"mood": 1 - entry["severity"], "events": events}
    return result


def disaster_for(name, disaster_map):
    return disaster_map.get(name, {"mood": 1, "events": []})


def compute_country(c, disasters):
    """Fetch weather + both news-tone categories for one country and compute
    its final score. Weather, econ, and pol are fetched in their own threads
    too, so one slow GDELT call doesn't block the (fast, reliable) weather
    call for the same country."""
    try:
        with ThreadPoolExecutor(max_workers=3) as inner:
            weather_future = inner.submit(fetch_weather, c)
            econ_future = inner.submit(fetch_tone, c["fips"], "economy OR inflation OR jobs OR markets")
            pol_future = inner.submit(fetch_tone, c["fips"], "government OR election OR parliament OR political")
            weather = weather_future.result()
            econ = econ_future.result()
            pol = pol_future.result()
    except Exception as e:
        return c["name"], None, f"weather fetch failed: {e}"

    news_blocked = econ is None or pol is None
    if econ is None: econ = {"tone": 0, "mood": 0.5, "unavailable": True}
    if pol is None: pol = {"tone": 0, "mood": 0.5, "unavailable": True}

    baseline = baseline_for(c["name"])
    disaster = disaster_for(c["name"], disasters)
    score = (baseline["score"]/10)*0.50 + weather["mood"]*0.12 + econ["mood"]*0.12 + pol["mood"]*0.12 + disaster["mood"]*0.14

    record = {
        "score": score, "baseline": baseline, "weather": weather,
        "econ": econ, "pol": pol, "disaster": disaster, "newsBlocked": news_blocked,
    }
    return c["name"], record, None


def main():
    start_time = time.time()
    print(f"=== Global Mood Map index computer — {datetime.now().isoformat()} ===\n")

    disasters = fetch_disasters()

    print("\nFetching life expectancy (World Bank)...")
    life_exp = fetch_life_expectancy()

    print("\nFetching oldest living person per country (GRG)...")
    oldest_living = fetch_oldest_living()

    print(f"\nComputing full index for {len(COUNTRIES)} countries "
          f"({COUNTRY_WORKERS} in parallel, GDELT capped at {GDELT_MAX_CONCURRENT} concurrent)...")
    countries_out = {}
    done = 0
    with ThreadPoolExecutor(max_workers=COUNTRY_WORKERS) as pool:
        futures = {pool.submit(compute_country, c, disasters): c for c in COUNTRIES}
        for future in as_completed(futures):
            c = futures[future]
            name, record, error = future.result()
            done += 1
            elapsed = time.time() - start_time
            if record:
                record["longevity"] = longevity_for(name, life_exp, oldest_living)
                countries_out[name] = record
                print(f"[{done}/{len(COUNTRIES)}] {name} — score {record['score']*10:.1f}/10 ({elapsed:.0f}s elapsed)")
            else:
                print(f"[{done}/{len(COUNTRIES)}] {name} — skipped ({error}) ({elapsed:.0f}s elapsed)")

    output = {
        "savedAt": int(time.time() * 1000),
        "generatedAtIso": datetime.now(timezone.utc).isoformat(),
        "countries": countries_out,
    }
    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)

    total_elapsed = time.time() - start_time
    print(f"\n=== Done in {total_elapsed:.0f}s. {len(countries_out)}/{len(COUNTRIES)} countries computed. "
          f"Written to {OUTPUT_FILE} ===")


if __name__ == "__main__":
    main()
