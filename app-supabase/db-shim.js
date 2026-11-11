// Small adapter: gives the app a document-database style API (collection/doc/set/onSnapshot/batch)
// on top of one Supabase table called "docs" (collection, id, data jsonb).
(function () {
  const codeOf = (e) => e.code === "42501" ? "permission-denied" : /fetch|network/i.test(e.message || "") ? "unavailable" : e.code || "error";
  const fail = (e) => Object.assign(new Error(e.message), { code: codeOf(e) });
  window.makeDb = function (sb) {
    function listen(c, load) {
      load();
      sb.channel("c-" + c + "-" + Math.random().toString(36).slice(2))
        .on("postgres_changes", { event: "*", schema: "public", table: "docs", filter: "collection=eq." + c }, () => load())
        .subscribe();
    }
    function docRef(c, id) {
      return {
        _c: c, _id: id,
        async set(d, o) {
          let body = d;
          if (o && o.merge) {
            const { data } = await sb.from("docs").select("data").eq("collection", c).eq("id", id).maybeSingle();
            body = { ...((data && data.data) || {}), ...d };
          }
          const { error } = await sb.from("docs").upsert({ collection: c, id, data: body });
          if (error) throw fail(error);
        },
        onSnapshot(next, err) {
          listen(c, async () => {
            const { data, error } = await sb.from("docs").select("data").eq("collection", c).eq("id", id).maybeSingle();
            if (error) { err && err(fail(error)); return; }
            next({ exists: !!data, data: () => data && data.data });
          });
        },
      };
    }
    function collection(c) {
      return {
        doc: (id) => docRef(c, id),
        onSnapshot(next, err) {
          listen(c, async () => {
            const { data, error } = await sb.from("docs").select("id,data").eq("collection", c);
            if (error) { err && err(fail(error)); return; }
            const docs = data.map((r) => ({ id: r.id, data: () => r.data }));
            next({ docs, empty: !docs.length });
          });
        },
      };
    }
    return {
      collection,
      doc: (path) => { const [c, ...r] = path.split("/"); return docRef(c, r.join("/")); },
      batch() {
        const rows = [];
        return {
          set(ref, d) { rows.push({ collection: ref._c, id: ref._id, data: d }); },
          async commit() { const { error } = await sb.from("docs").upsert(rows); if (error) throw fail(error); },
        };
      },
    };
  };
})();
