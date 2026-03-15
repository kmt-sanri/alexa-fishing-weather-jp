import logging
import requests
import datetime
from ask_sdk_core.skill_builder import CustomSkillBuilder
from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.utils import is_request_type, is_intent_name

# 気象庁の地点記号と、Open-Meteo用の緯度経度を設定
STATIONS = {
    "土佐清水": {"code": "TS", "lat": 32.78, "lon": 132.95},
    "宇和島": {"code": "UW", "lat": 33.22, "lon": 132.56},
    "足摺岬": {"code": "TS", "lat": 32.72, "lon": 133.02}, 
    "室戸岬": {"code": "MU", "lat": 33.24, "lon": 134.17},
    "高知": {"code": "KC", "lat": 33.50, "lon": 133.56}
}

def get_fishing_info(station_name):
    info = STATIONS.get(station_name, STATIONS["高知"])
    code = info["code"]
    lat = info["lat"]
    lon = info["lon"]
    
    now_utc = datetime.datetime.utcnow()
    now_jst = now_utc + datetime.timedelta(hours=9)
    year_str = now_jst.strftime("%Y")
    target_date = f"{now_jst.strftime('%y')}{now_jst.month:2d}{now_jst.day:2d}"

    speech_parts = [f"今日の{station_name}の釣り情報です。"]

    # --- 1. 潮の高さ（気象庁） ---
    tide_url = f"https://www.data.jma.go.jp/kaiyou/data/db/tide/suisan/txt/{year_str}/{code}.txt"
    try:
        res_tide = requests.get(tide_url, timeout=5)
        if res_tide.status_code == 200:
            today_data = None
            for line in res_tide.text.splitlines():
                if len(line) >= 78 and line[72:78] == target_date:
                    today_data = line
                    break
            
            if today_data:
                high_tides = []
                for i in range(4):
                    start = 80 + i * 7
                    chunk = today_data[start:start+7]
                    if chunk != "9999999" and chunk.strip() != "":
                        hour = int(chunk[0:2])
                        minute = int(chunk[2:4])
                        high_tides.append(f"{hour}時{minute}分")
                if high_tides:
                    speech_parts.append(f"満潮は、{'と、'.join(high_tides)}です。")
    except Exception as e:
        logging.error(f"Tide Error: {e}")

    # --- 2. 天気・気温・風・日の出日の入り（Open-Meteo Weather API） ---
    # 風速をm/sで取得するためのパラメータ(wind_speed_unit=ms)を追加
    weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&daily=sunrise,sunset,temperature_2m_max,temperature_2m_min&hourly=wind_speed_10m&timezone=Asia%2FTokyo&forecast_days=1&wind_speed_unit=ms"
    try:
        res_wea = requests.get(weather_url, timeout=5)
        if res_wea.status_code == 200:
            w_data = res_wea.json()
            daily = w_data["daily"]
            hourly = w_data["hourly"]

            # 日の出・日の入り (形式: "2026-03-15T06:14" -> "6時14分")
            sunrise_str = daily["sunrise"][0][-5:]
            sunset_str = daily["sunset"][0][-5:]
            sr_h, sr_m = int(sunrise_str[:2]), int(sunrise_str[3:])
            ss_h, ss_m = int(sunset_str[:2]), int(sunset_str[3:])
            speech_parts.append(f"日の出は{sr_h}時{sr_m}分、日の入りは{ss_h}時{ss_m}分。")

            # 気温
            temp_max = round(daily["temperature_2m_max"][0])
            temp_min = round(daily["temperature_2m_min"][0])
            speech_parts.append(f"気温は{temp_min}度から{temp_max}度。")

            # 日中（5時〜17時）の最大風速
            day_winds = hourly["wind_speed_10m"][5:18]
            max_wind = round(max(day_winds))
            speech_parts.append(f"日中の風は、最大で秒速{max_wind}メートルの見込みです。")
    except Exception as e:
        logging.error(f"Weather Error: {e}")

    # --- 3. 波の高さ（Open-Meteo Marine API） ---
    marine_url = f"https://marine-api.open-meteo.com/v1/marine?latitude={lat}&longitude={lon}&hourly=wave_height&timezone=Asia%2FTokyo&forecast_days=1"
    try:
        res_mar = requests.get(marine_url, timeout=5)
        if res_mar.status_code == 200:
            m_data = res_mar.json()
            waves = m_data["hourly"]["wave_height"]
            
            # 5時から17時のデータを抽出（Noneが含まれる場合の除外処理）
            day_waves = [w for w in waves[5:18] if w is not None]
            
            if day_waves:
                min_wave = min(day_waves)
                max_wave = max(day_waves)
                # 最大波高になる時間を算出（5時スタートなのでインデックス+5）
                max_hour = 5 + day_waves.index(max_wave)
                
                speech_parts.append(f"5時から17時の波の高さは、{min_wave}メートルから{max_wave}メートルで、最大は{max_hour}時ごろの予測です。")
    except Exception as e:
        logging.error(f"Marine Error: {e}")

    # 取得できたテキストを繋げて返す
    return " ".join(speech_parts)

class TideIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("TideIntent")(handler_input)

    def handle(self, handler_input):
        slots = handler_input.request_envelope.request.intent.slots
        place = slots["Place"].value if "Place" in slots and slots["Place"].value else "高知"
        speech_text = get_fishing_info(place)
        return handler_input.response_builder.speak(speech_text).response

class LaunchRequestHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_request_type("LaunchRequest")(handler_input)

    def handle(self, handler_input):
        speech_text = "潮の高さです。土佐清水や宇和島など、どこを知りたいですか？"
        return handler_input.response_builder.speak(speech_text).ask(speech_text).response

sb = CustomSkillBuilder()
sb.add_request_handler(LaunchRequestHandler())
sb.add_request_handler(TideIntentHandler())
lambda_handler = sb.lambda_handler()
