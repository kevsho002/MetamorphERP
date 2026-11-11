import { useEffect, useMemo, useState } from "react";
import { rosterApi } from "../api.js";

// Caché por pestaña: la configuración del roster cambia poco (se edita en /admin/).
let cache = null;
let inflight = null;

function load() {
  if (cache) return Promise.resolve(cache);
  if (!inflight) {
    inflight = Promise.all([rosterApi.attributes(), rosterApi.dimensions()])
      .then(([attributes, dimensions]) => {
        cache = { attributes, dimensions };
        return cache;
      })
      .finally(() => {
        inflight = null;
      });
  }
  return inflight;
}

/** Atributos activos del roster y catálogos de sus dimensiones (clientes, marcas, líneas...). */
export function useRosterConfig() {
  const [state, setState] = useState({ data: cache, loading: !cache, error: null });

  useEffect(() => {
    if (cache) return undefined;
    let alive = true;
    load()
      .then((data) => alive && setState({ data, loading: false, error: null }))
      .catch((err) => alive && setState({ data: null, loading: false, error: err.message }));
    return () => {
      alive = false;
    };
  }, []);

  return useMemo(() => {
    const attributes = state.data?.attributes ?? [];
    const dimensions = Object.fromEntries((state.data?.dimensions ?? []).map((d) => [d.code, d]));
    const groups = [];
    attributes.forEach((a) => {
      let group = groups.find((g) => g.name === a.group);
      if (!group) groups.push((group = { name: a.group, attributes: [] }));
      group.attributes.push(a);
    });
    return {
      ...state,
      attributes,
      groups,
      dimensions,
      byCode: Object.fromEntries(attributes.map((a) => [a.code, a])),
      /** Opciones de un atributo de dimensión: país del empleado y valor vigente del atributo padre. */
      optionsFor: (attribute, { country, parentValue } = {}) => {
        const items = dimensions[attribute.dimension]?.items ?? [];
        return items.filter(
          (i) => (!i.country || !country || i.country === country) && (!attribute.depends_on || i.parent === parentValue),
        );
      },
    };
  }, [state]);
}
