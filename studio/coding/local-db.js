// Local database: the same collection/doc API the app uses, stored by the Studio server on this computer.
(function () {
  window.makeLocalDb = function () {
    const api = async (method, url, body) => {
      let r;
      try { r = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) }); }
      catch (e) { throw Object.assign(new Error("offline"), { code: "unavailable" }); }
      if (!r.ok) throw Object.assign(new Error("error " + r.status), { code: "unavailable" });
      return r.json();
    };
    const loaders = new Set();
    const tick = () => loaders.forEach((f) => f());
    setInterval(tick, 2500);
    const watch = (load) => { loaders.add(load); load(); };
    function docRef(c, id) {
      return {
        _c: c, _id: id,
        async set(d, o) {
          let body = d;
          if (o && o.merge) { const cur = (await api("GET", `/api/db/${c}/${id}`)).data; body = { ...(cur || {}), ...d }; }
          await api("PUT", `/api/db/${c}/${id}`, body); tick();
        },
        onSnapshot(next, err) {
          let last;
          watch(async () => {
            try {
              const r = await api("GET", `/api/db/${c}/${id}`); const s = JSON.stringify(r);
              if (s === last) return; last = s;
              next({ exists: !!r.data, data: () => r.data });
            } catch (e) { err && err(e); }
          });
        },
      };
    }
    function collection(c) {
      return {
        doc: (id) => docRef(c, id),
        onSnapshot(next, err) {
          let last;
          watch(async () => {
            try {
              const rows = await api("GET", `/api/db/${c}`); const s = JSON.stringify(rows);
              if (s === last) return; last = s;
              const docs = rows.map((r) => ({ id: r.id, data: () => r.data }));
              next({ docs, empty: !docs.length });
            } catch (e) { err && err(e); }
          });
        },
      };
    }
    return {
      collection,
      doc: (path) => { const [c, ...r] = path.split("/"); return docRef(c, r.join("/")); },
      batch() { const ops = []; return { set(ref, d) { ops.push([ref, d]); }, async commit() { for (const [ref, d] of ops) await ref.set(d); } }; },
    };
  };
})();
