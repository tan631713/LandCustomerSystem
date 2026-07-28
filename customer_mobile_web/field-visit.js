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

  function buildGoogleMapsNavigationUrl(destination = {}, origin = null) {
    let value = "";
    if (validCoordinates(destination.latitude, destination.longitude)) {
      value = coordinateValue(destination.latitude, destination.longitude);
    } else {
      value = normalizedAddress(destination.address);
    }
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
    url.searchParams.set("travelmode", "driving");
    url.searchParams.set("dir_action", "navigate");
    return url.toString();
  }

  function openGoogleMapsNavigation(destination, origin = null) {
    const url = buildGoogleMapsNavigationUrl(destination, origin);
    window.location.assign(url);
    return url;
  }

  window.LCSFieldVisit = Object.freeze({
    buildGoogleMapsNavigationUrl,
    openGoogleMapsNavigation,
    positionErrorMessage,
    requestCurrentPosition,
    validCoordinates
  });
})();
