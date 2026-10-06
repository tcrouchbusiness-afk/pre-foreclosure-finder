// Run on the Landmark Web results page (Document Type = LP, page size "All").
// Reads the visible results table and downloads it as JSON. Move the file into data/raw/.
// Column positions verified on Martin County Landmark Web 2026-10-05; check one row if your county differs.
(() => {
  const t = document.getElementById('resultsTable');
  if (!t) return 'No #resultsTable on this page. Run the LP search first and set page size to All.';
  const rows = [...t.querySelectorAll('tbody tr')]
    .map(tr => [...tr.cells].map(c => c.innerText.trim().replace(/\s*\n\s*/g, ' ; ')))
    .filter(r => /^\d+$/.test(r[0]));
  const recs = rows.map(r => ({
    n: r[0], grantor: r[5], grantee: r[6], date: r[7], book: r[10], page: r[11], cfn: r[12],
    legal: r[14], lot: r[15], block: r[17], unit: r[18], subdiv: r[19],
  }));
  const shown = (document.body.innerText.match(/Returned (\d+) records of (\d+)/) || []);
  const today = new Date().toISOString().slice(0, 10);
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(recs, null, 1)], { type: 'application/json' }));
  a.download = `lis_pendens_${today}.json`;
  document.body.appendChild(a); a.click();
  return `${recs.length} rows extracted (page says: ${shown[0] || 'unknown'}). Sample: ${JSON.stringify(recs[0])}`;
})();
