import { useEffect, useMemo, useState } from "react";
import { generalIdsApi } from "../api.js";

let cache = null;

/**
 * Herramientas, tipos de ID (con restricciones por cliente/marca) y clientes con sus marcas.
 * `scopeFor(type)` replica la regla en cascada del backend para filtrar las listas:
 *   sin restricciones -> todo; cliente habilitado -> el cliente y TODAS sus marcas; marca habilitada -> solo esa marca.
 */
export function useGeneralIdCatalogs() {
  const [state, setState] = useState({ loading: !cache, data: cache, error: null });

  useEffect(() => {
    if (cache) return undefined;
    const controller = new AbortController();
    generalIdsApi
      .catalogs({ signal: controller.signal })
      .then((data) => {
        cache = data;
        setState({ loading: false, data, error: null });
      })
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    return () => controller.abort();
  }, []);

  return useMemo(() => {
    const data = state.data ?? { tools: [], types: [], clients: [] };
    const types = Object.fromEntries(data.types.map((t) => [t.code, t]));
    const scopeFor = (type) => {
      const applies = type?.applies_to ?? { all: true, clients: [], brands: [] };
      const clientOk = (c) => applies.all || applies.clients.includes(c.code) || c.brands.some((b) => applies.brands.includes(b.code));
      const brandOk = (c, b) => applies.all || applies.clients.includes(c.code) || applies.brands.includes(b.code);
      const clients = data.clients.filter(clientOk).map((c) => ({ ...c, brands: c.brands.filter((b) => b.is_active && brandOk(c, b)) }));
      return { clients, clientNeedsBrand: (c) => !applies.all && !applies.clients.includes(c.code) };
    };
    return { ...state, ...data, typesByCode: types, scopeFor };
  }, [state]);
}
