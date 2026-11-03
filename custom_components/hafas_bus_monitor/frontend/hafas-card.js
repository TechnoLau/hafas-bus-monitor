class HafasDepartureCard extends HTMLElement {
  setConfig(config) {
    if (!config || !config.entity) {
      throw new Error("Bitte eine entity angeben");
    }
    this._config = config;
    if (!this._card) {
      this._card = document.createElement("ha-card");
      this._card.style.padding = "14px 16px";
      this._card.style.overflow = "hidden";
      this._departure = document.createElement("div");
      this._departure.style.fontSize = "30px";
      this._departure.style.fontWeight = "700";
      this._departure.style.lineHeight = "1.15";
      this._departure.style.whiteSpace = "nowrap";
      this._departure.style.overflow = "hidden";
      this._departure.style.textOverflow = "ellipsis";
      this._stop = document.createElement("div");
      this._stop.style.fontSize = "13px";
      this._stop.style.lineHeight = "1.3";
      this._stop.style.marginTop = "4px";
      this._stop.style.color = "var(--secondary-text-color)";
      this._stop.style.whiteSpace = "nowrap";
      this._stop.style.overflow = "hidden";
      this._stop.style.textOverflow = "ellipsis";
      this._card.appendChild(this._departure);
      this._card.appendChild(this._stop);
      this.appendChild(this._card);
    }
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._config || !this._card) return;
    const stateObj = hass.states[this._config.entity];
    if (!stateObj) {
      this._departure.textContent = "Entität nicht gefunden";
      this._stop.textContent = this._config.entity;
      return;
    }
    this._departure.textContent = stateObj.state;
    this._stop.textContent =
      stateObj.attributes.stop ||
      stateObj.attributes.friendly_name ||
      this._config.entity;
  }

  getCardSize() {
    return 2;
  }

  static getStubConfig() {
    return { entity: "sensor.hafas_hospitalstrasse" };
  }
}

if (!customElements.get("hafas-departure-card")) {
  customElements.define("hafas-departure-card", HafasDepartureCard);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "hafas-departure-card")) {
  window.customCards.push({
    type: "hafas-departure-card",
    name: "HAFAS Abfahrt",
    description: "Große Abfahrt, darunter klein die Haltestelle",
    preview: true,
  });
}
