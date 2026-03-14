import aiohttp
import logging
from config import GEOCODER_API_KEY

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def reverse_geocode(lat: float, lon: float) -> str | None:
    """
    Преобразует координаты в адрес через Яндекс.Геокодер
    """
    if not GEOCODER_API_KEY:
        logger.warning("GEOCODER_API_KEY не настроен")
        return None
    
    # Яндекс использует формат "долгота,широта"
    url = "https://geocode-maps.yandex.ru/1.x/"
    params = {
        "apikey": GEOCODER_API_KEY,
        "geocode": f"{lon},{lat}",
        "format": "json",
        "lang": "ru_RU",
        "results": 1  # только один результат
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Парсим ответ Яндекс.Геокодера
                    try:
                        feature_member = data['response']['GeoObjectCollection']['featureMember']
                        if feature_member:
                            geo_object = feature_member[0]['GeoObject']
                            address = geo_object['metaDataProperty']['GeocoderMetaData']['text']
                            
                            # Дополнительно можем получить более детальную информацию
                            logger.info(f"Найден адрес: {address}")
                            return address
                        else:
                            logger.warning("Адрес не найден")
                            return None
                            
                    except (KeyError, IndexError) as e:
                        logger.error(f"Ошибка парсинга ответа геокодера: {e}")
                        return None
                else:
                    logger.error(f"Ошибка геокодера: HTTP {response.status}")
                    return None
                    
    except aiohttp.ClientError as e:
        logger.error(f"Ошибка соединения с геокодером: {e}")
        return None
    except asyncio.TimeoutError:
        logger.error("Таймаут при запросе к геокодеру")
        return None
    except Exception as e:
        logger.error(f"Неожиданная ошибка: {e}")
        return None

async def geocode_address(address: str) -> tuple[float, float] | None:
    """
    Преобразует адрес в координаты (прямое геокодирование)
    Может пригодиться для будущих функций
    """
    if not GEOCODER_API_KEY:
        return None
    
    url = "https://geocode-maps.yandex.ru/1.x/"
    params = {
        "apikey": GEOCODER_API_KEY,
        "geocode": address,
        "format": "json",
        "lang": "ru_RU",
        "results": 1
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    try:
                        feature_member = data['response']['GeoObjectCollection']['featureMember']
                        if feature_member:
                            pos = feature_member[0]['GeoObject']['Point']['pos']
                            lon, lat = map(float, pos.split())
                            return (lat, lon)
                    except (KeyError, IndexError, ValueError) as e:
                        logger.error(f"Ошибка парсинга координат: {e}")
                        return None
    except Exception as e:
        logger.error(f"Ошибка геокодирования адреса: {e}")
        return None
    
    return None
