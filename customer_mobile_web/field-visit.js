"use strict";

(() => {
  const DEFAULT_GEOLOCATION_OPTIONS = Object.freeze({
    enableHighAccuracy: true,
    timeout: 12000,
    maximumAge: 30000
  });

  function finiteNumber(value) {
    if (value === null || value === undefined) return null;
    if (typeof value === "string" && !value.trim()) return null;
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function validCoordinates(latitude, longitude) {
    const lat = finiteNumber(latitude);
    const lon = finiteNumber(longitude);
    return lat !== null
      && lon !== null
      && lat >= -90
      && lat <= 90
      && lon >= -180
      && lon <= 180;
  }

  function positionErrorMessage(error) {
    const code = Number(error && error.code);
    if (code === 1) return "尚未允許定位。請在 Safari 網站設定中允許位置權限後重試。";
    if (code === 2) return "目前無法取得位置。請確認已開啟定位服務，並移到訊號較好的地方重試。";
    if (code === 3) return "取得位置逾時。請稍候再按一次定位。";
    return "無法取得目前位置，仍可沿用原始拜訪順序。";
  }

  function requestCurrentPosition(options = DEFAULT_GEOLOCATION_OPTIONS) {
    if (window.isSecureContext === false) {
      return Promise.reject(new Error("定位功能需要使用 HTTPS 安全連線。"));
    }
    if (!navigator.geolocation) {
      return Promise.reject(new Error("這個瀏覽器不支援 GPS 定位，仍可沿用原始拜訪順序。"));
    }
    return new Promise((resolve, reject) => {
      navigator.geolocation.getCurrentPosition(
        position => {
          const latitude = finiteNumber(position && position.coords && position.coords.latitude);
          const longitude = finiteNumber(position && position.coords && position.coords.longitude);
          if (!validCoordinates(latitude, longitude)) {
            reject(new Error("手機回傳的定位資料無效，請重新取得位置。"));
            return;
          }
          resolve({
            latitude,
            longitude,
            accuracy_m: finiteNumber(position.coords.accuracy),
            captured_at: new Date(position.timestamp || Date.now()).toISOString()
          });
        },
        error => reject(new Error(positionErrorMessage(error))),
        { ...DEFAULT_GEOLOCATION_OPTIONS, ...options }
      );
    });
  }

  function coordinateValue(latitude, longitude) {
    if (!validCoordinates(latitude, longitude)) return "";
    return `${Number(latitude)},${Number(longitude)}`;
  }

  function normalizedAddress(value) {
    return String(value || "")
      .replace(/[\r\n\t]+/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  // Motorcycles are the default field vehicle.  Google Maps falls back to
  // driving directions where two-wheeler routing is not offered.
  const DEFAULT_TRAVEL_MODE = "two-wheeler";
  const TRAVEL_MODES = Object.freeze(["two-wheeler", "driving", "walking", "bicycling", "transit"]);
  // Google Maps URLs accept 3 waypoints when opened in a mobile browser and
  // 9 elsewhere.  The phone is the primary device, so stay within 3.
  const MOBILE_MAX_WAYPOINTS = 3;
  const DESKTOP_MAX_WAYPOINTS = 9;
  const DEFAULT_SCHEDULE = Object.freeze({
    speedKmh: 30,
    detourFactor: 1.4,
    dwellMinutes: 20
  });

  function travelModeValue(value) {
    const mode = String(value || "").trim().toLowerCase();
    return TRAVEL_MODES.includes(mode) ? mode : DEFAULT_TRAVEL_MODE;
  }

  function placeValue(place) {
    if (!place) return "";
    if (validCoordinates(place.latitude, place.longitude)) {
      return coordinateValue(place.latitude, place.longitude);
    }
    return normalizedAddress(place.address);
  }

  function buildGoogleMapsNavigationUrl(destination = {}, origin = null, options = {}) {
    const value = placeValue(destination);
    if (!value) {
      throw new Error("這位地主沒有座標或地址，暫時無法開啟導航。");
    }
    const url = new URL("https://www.google.com/maps/dir/");
    url.searchParams.set("api", "1");
    const originValue = coordinateValue(
      origin && origin.latitude,
      origin && origin.longitude
    );
    if (originValue) url.searchParams.set("origin", originValue);
    url.searchParams.set("destination", value);
    url.searchParams.set("travelmode", travelModeValue(options.travelMode));
    url.searchParams.set("dir_action", "navigate");
    return url.toString();
  }

  function sameStopKey(item) {
    const ownerId = Number(item && item.owner_id);
    return Number.isFinite(ownerId) && ownerId > 0 ? `owner:${ownerId}` : "";
  }

  function sameStop(left, right) {
    if (!left || !right) return false;
    const leftOwner = sameStopKey(left);
    if (leftOwner && leftOwner === sameStopKey(right)) return true;
    const leftAddress = normalizedAddress(left.address).replace(/\s+/g, "");
    if (leftAddress && leftAddress === normalizedAddress(right.address).replace(/\s+/g, "")) {
      return true;
    }
    return validCoordinates(left.latitude, left.longitude)
      && validCoordinates(right.latitude, right.longitude)
      && Number(left.latitude) === Number(right.latitude)
      && Number(left.longitude) === Number(right.longitude);
  }

  // Consecutive route items at the same owner, address or coordinate are one
  // physical stop.  The server keeps land shares of one owner next to each
  // other when it plans the route, so grouping neighbours is sufficient.
  function groupFieldVisitStops(items = []) {
    const stops = [];
    (items || []).forEach((item, index) => {
      const previous = stops[stops.length - 1];
      if (previous && sameStop(previous.items[previous.items.length - 1], item)) {
        previous.items.push(item);
        previous.indexes.push(index);
        if (!validCoordinates(previous.latitude, previous.longitude)
          && validCoordinates(item.latitude, item.longitude)) {
          previous.latitude = Number(item.latitude);
          previous.longitude = Number(item.longitude);
        }
        if (!normalizedAddress(previous.address) && normalizedAddress(item.address)) {
          previous.address = normalizedAddress(item.address);
        }
        return;
      }
      stops.push({
        number: stops.length + 1,
        items: [item],
        indexes: [index],
        latitude: validCoordinates(item.latitude, item.longitude) ? Number(item.latitude) : null,
        longitude: validCoordinates(item.latitude, item.longitude) ? Number(item.longitude) : null,
        address: normalizedAddress(item.address)
      });
    });
    return stops;
  }

  function stopForIndex(stops, index) {
    return (stops || []).find(stop => stop.indexes.includes(Number(index))) || null;
  }

  function haversineKm(latitudeA, longitudeA, latitudeB, longitudeB) {
    const radians = value => Number(value) * Math.PI / 180;
    const deltaLatitude = radians(latitudeB) - radians(latitudeA);
    const deltaLongitude = radians(longitudeB) - radians(longitudeA);
    const value = Math.sin(deltaLatitude / 2) ** 2
      + Math.cos(radians(latitudeA)) * Math.cos(radians(latitudeB))
      * Math.sin(deltaLongitude / 2) ** 2;
    return 2 * 6371.0088 * Math.asin(Math.sqrt(Math.min(1, value)));
  }

  function positiveNumber(value, fallback) {
    const number = finiteNumber(value);
    return number !== null && number > 0 ? number : fallback;
  }

  // Rough arrival times from straight-line distance.  This is only a planning
  // aid; the navigation app remains the source of real travel time.
  function estimateStopSchedule(stops = [], options = {}) {
    const speedKmh = positiveNumber(options.speedKmh, DEFAULT_SCHEDULE.speedKmh);
    const detourFactor = positiveNumber(options.detourFactor, DEFAULT_SCHEDULE.detourFactor);
    const dwellMinutes = finiteNumber(options.dwellMinutes) !== null && Number(options.dwellMinutes) >= 0
      ? Number(options.dwellMinutes)
      : DEFAULT_SCHEDULE.dwellMinutes;
    const departAt = options.departAt ? new Date(options.departAt) : new Date();
    let clock = Number.isNaN(departAt.getTime()) ? Date.now() : departAt.getTime();
    let point = options.origin && validCoordinates(options.origin.latitude, options.origin.longitude)
      ? { latitude: Number(options.origin.latitude), longitude: Number(options.origin.longitude) }
      : null;
    let approximate = false;
    let totalKm = 0;
    const schedule = (stops || []).map(stop => {
      const hasCoordinate = validCoordinates(stop.latitude, stop.longitude);
      let legKm = null;
      if (hasCoordinate && point) {
        legKm = haversineKm(point.latitude, point.longitude, stop.latitude, stop.longitude)
          * detourFactor;
        totalKm += legKm;
        clock += (legKm / speedKmh) * 3600000;
      } else {
        approximate = true;
      }
      if (hasCoordinate) point = { latitude: Number(stop.latitude), longitude: Number(stop.longitude) };
      const arrival = new Date(clock);
      const visitMinutes = dwellMinutes * Math.max(1, (stop.items || []).length);
      clock += visitMinutes * 60000;
      return {
        stop,
        legKm,
        arrivalAt: arrival,
        departAt: new Date(clock),
        approximate
      };
    });
    return {
      items: schedule,
      totalKm,
      finishAt: new Date(clock),
      speedKmh,
      detourFactor,
      dwellMinutes
    };
  }

  // Whole-day navigation.  Each segment continues from the previous
  // segment's destination; the first one starts from the phone's location
  // unless an origin is given.
  function buildGoogleMapsRouteSegments(stops = [], options = {}) {
    const maxWaypoints = Math.max(
      0,
      Math.floor(positiveNumber(options.maxWaypoints, MOBILE_MAX_WAYPOINTS))
    );
    const places = (stops || [])
      .map(stop => ({ stop, value: placeValue(stop) }))
      .filter(entry => entry.value);
    const segments = [];
    let origin = options.origin && validCoordinates(options.origin.latitude, options.origin.longitude)
      ? { value: coordinateValue(options.origin.latitude, options.origin.longitude), stop: null }
      : null;
    let cursor = 0;
    while (cursor < places.length) {
      const chunk = places.slice(cursor, cursor + maxWaypoints + 1);
      const destination = chunk[chunk.length - 1];
      const waypoints = chunk.slice(0, -1);
      const url = new URL("https://www.google.com/maps/dir/");
      url.searchParams.set("api", "1");
      if (origin) url.searchParams.set("origin", origin.value);
      url.searchParams.set("destination", destination.value);
      if (waypoints.length) {
        url.searchParams.set("waypoints", waypoints.map(entry => entry.value).join("|"));
      }
      url.searchParams.set("travelmode", travelModeValue(options.travelMode));
      segments.push({
        number: segments.length + 1,
        url: url.toString(),
        firstStop: chunk[0].stop,
        lastStop: destination.stop,
        stopCount: chunk.length
      });
      origin = destination;
      cursor += chunk.length;
    }
    return segments;
  }

  function parseDegrees(value) {
    const match = String(value || "").trim().match(
      /^(\d{1,3})\s*[°º]\s*(\d{1,2})\s*['′]\s*(\d{1,2}(?:\.\d+)?)\s*["″]?\s*([NSEW])$/i
    );
    if (!match) return null;
    let number = Number(match[1]) + Number(match[2]) / 60 + Number(match[3]) / 3600;
    if (/[SW]/i.test(match[4])) number = -number;
    return { value: number, axis: /[NS]/i.test(match[4]) ? "lat" : "lng" };
  }

  // Accepts what people usually copy from Google Maps: "25.0330, 121.5654",
  // a long Google Maps link, or degrees-minutes-seconds text.
  function parseCoordinateInput(input) {
    const raw = String(input || "").trim();
    if (!raw) throw new Error("請貼上座標，例如 25.0330, 121.5654。");
    if (/maps\.app\.goo\.gl|goo\.gl\/maps/i.test(raw)) {
      throw new Error("短網址無法直接讀取座標。請在 Google 地圖長按該位置，複製上方顯示的「緯度, 經度」再貼上。");
    }
    let decoded = raw;
    try { decoded = decodeURIComponent(raw); } catch (_error) { decoded = raw; }
    const patterns = [
      /!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)/,
      /@(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)/,
      /[?&](?:q|query|ll|destination|center)=(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)/,
      /^\(?\s*(-?\d+(?:\.\d+)?)\s*[,，\s]\s*(-?\d+(?:\.\d+)?)\s*\)?$/
    ];
    let pair = null;
    for (const pattern of patterns) {
      const match = decoded.match(pattern);
      if (match) {
        pair = [Number(match[1]), Number(match[2])];
        break;
      }
    }
    if (!pair) {
      const parts = decoded.split(/\s*[,，]\s*|\s+(?=\d{1,3}\s*[°º])/).map(parseDegrees);
      if (parts.length === 2 && parts[0] && parts[1]) {
        const lat = parts.find(part => part.axis === "lat");
        const lng = parts.find(part => part.axis === "lng");
        if (lat && lng) pair = [lat.value, lng.value];
      }
    }
    if (!pair) throw new Error("看不懂這個座標。請貼上「緯度, 經度」，例如 25.0330, 121.5654。");
    let [latitude, longitude] = pair;
    // People sometimes paste longitude first; latitude can never exceed 90.
    if (Math.abs(latitude) > 90 && Math.abs(longitude) <= 90) {
      [latitude, longitude] = [longitude, latitude];
    }
    if (!validCoordinates(latitude, longitude)) {
      throw new Error("座標超出範圍，請確認緯度在 -90～90、經度在 -180～180 之間。");
    }
    return {
      latitude: Math.round(latitude * 1e7) / 1e7,
      longitude: Math.round(longitude * 1e7) / 1e7,
      outsideTaiwan: !(latitude >= 21 && latitude <= 27 && longitude >= 117 && longitude <= 123)
    };
  }

  function openGoogleMapsNavigation(destination, origin = null, options = {}) {
    const url = buildGoogleMapsNavigationUrl(destination, origin, options);
    window.location.assign(url);
    return url;
  }

  window.LCSFieldVisit = Object.freeze({
    DEFAULT_SCHEDULE,
    DEFAULT_TRAVEL_MODE,
    DESKTOP_MAX_WAYPOINTS,
    MOBILE_MAX_WAYPOINTS,
    buildGoogleMapsNavigationUrl,
    buildGoogleMapsRouteSegments,
    estimateStopSchedule,
    groupFieldVisitStops,
    openGoogleMapsNavigation,
    parseCoordinateInput,
    positionErrorMessage,
    requestCurrentPosition,
    stopForIndex,
    validCoordinates
  });
})();
