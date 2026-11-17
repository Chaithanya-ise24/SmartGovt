// Use this for every POST so the CSRF token is always sent.
async function fetchJSON(url, data = null, method = "POST") {
  const token = document.querySelector('meta[name="csrf-token"]').content;
  const options = { method, headers: { "X-CSRFToken": token, "Content-Type": "application/json" } };
  if (data !== null) options.body = JSON.stringify(data);
  const res = await fetch(url, options);
  let body = {};
  try { body = await res.json(); } catch (e) {}
  if (!res.ok) throw new Error(body.error || "Something went wrong. Please try again.");
  return body;
}