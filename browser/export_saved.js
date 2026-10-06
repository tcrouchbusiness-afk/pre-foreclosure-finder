// Download everything save_case_page.js collected. Move the file into data/ccis/ (dockets)
// or data/probate/ (probate pages). Set BUCKET to match.
(() => {
  const BUCKET = '__fc_cases';
  const data = localStorage.getItem(BUCKET) || '{}';
  const name = (BUCKET === '__fc_probate' ? 'probate_' : 'ccis_cases_') + new Date().toISOString().slice(0, 10) + '.json';
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([data], { type: 'application/json' }));
  a.download = name;
  document.body.appendChild(a); a.click();
  return `${Object.keys(JSON.parse(data)).length} pages -> ${name}`;
})();
