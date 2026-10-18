(() => {
  "use strict";

  function numeric(value) {
    if (value === "" || value === null || typeof value === "boolean") throw new Error("请填写工况数值");
    const number = Number(value);
    if (!Number.isFinite(number)) throw new Error("工况数值必须有限");
    return number;
  }

  function factor(control, unit) {
    const option = control.unit_options.find((item) => item.unit === unit);
    if (!option || !Number.isFinite(option.factor_to_si) || option.factor_to_si <= 0) {
      throw new Error(`单位 ${unit} 不适用于 ${control.label || control.name}`);
    }
    return option.factor_to_si;
  }

  function convert(control, value, sourceUnit, targetUnit) {
    const converted = canonical(control, value, sourceUnit) / factor(control, targetUnit);
    if (!Number.isFinite(converted)) throw new Error("单位换算超出数值范围");
    return converted;
  }

  function canonical(control, value, unit) {
    const converted = numeric(value) * factor(control, unit);
    if (!Number.isFinite(converted)) throw new Error("单位换算超出数值范围");
    return converted;
  }

  function withinLimits(control, value, unit) {
    try {
      const converted = convert(control, value, unit, control.unit);
      return converted >= control.minimum && converted <= control.maximum;
    } catch {
      return false;
    }
  }

  const api = Object.freeze({ numeric, convert, canonical, withinLimits });
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else globalThis.FaultCrafterUnits = api;
})();
