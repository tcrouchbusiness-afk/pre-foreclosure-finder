// Run on a court case detail page (foreclosure or probate) after the human has searched it.
// Saves the page text into this browser's localStorage under a bucket. Nothing leaves the browser.
// Set BUCKET to '__fc_cases' for foreclosure dockets or '__fc_probate' for probate cases.
(() => {
  const BUCKET = '__fc_cases';
  const cn = (document.title.match(/^(\d{8}\w+)/) || [])[1];
  if (!cn) return 'Not on a case detail page: ' + document.title;
  const all = JSON.parse(localStorage.getItem(BUCKET) || '{}');
  all[cn] = { title: document.title, text: document.body.innerText.slice(0, 40000), pulled: new Date().toISOString() };
  localStorage.setItem(BUCKET, JSON.stringify(all));
  return `${Object.keys(all).length} saved in ${BUCKET}; last ${cn}`;
})();
