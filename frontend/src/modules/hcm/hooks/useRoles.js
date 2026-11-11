import { useEffect, useState } from "react";
import { useAuth } from "../../../auth/AuthContext.jsx";
import { usersApi } from "../../../services/usersApi.js";

let cache = null;

/** Roles que el usuario actual puede otorgar (GET /roles/, requiere users.view). */
export function useRoles() {
  const { hasPermission } = useAuth();
  const allowed = hasPermission("users.view");
  const [roles, setRoles] = useState(cache ?? []);

  useEffect(() => {
    if (!allowed || cache) return undefined;
    let alive = true;
    usersApi
      .roles()
      .then((data) => {
        cache = data;
        if (alive) setRoles(data);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [allowed]);

  return { roles, assignable: roles.filter((r) => r.assignable) };
}
