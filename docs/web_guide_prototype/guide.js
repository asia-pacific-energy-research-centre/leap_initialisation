const steps = [
  { target: 'target-upload', title: 'Start with the export', copy: 'Drop the LEAP Energy Balance workbook here. The web app reads the economy and scenario from the file, so there is no second metadata form to complete.' },
  { target: 'target-year', title: 'Choose the review year(s)', copy: 'Enter one year or several comma-separated years. This controls which balance tables are checked and which review workbooks are returned.' },
  { target: 'target-esto', title: 'Change the comparison dataset when needed', copy: 'Open this optional area when you have a different ESTO base table. It changes the comparison used by both the review workbook and the dashboard.' },
  { target: 'target-run', title: 'Build the review', copy: 'Start the run. Diagnostics, the four-sheet workbook, dashboard pages, and downloadable archives appear in the results area when processing finishes.' }
];
let current = 0;
const $ = id => document.getElementById(id);
function positionPopover(target) {
  const box = target.getBoundingClientRect();
  const pop = $('tour-popover');
  const left = Math.min(Math.max(16, box.left), window.innerWidth - pop.offsetWidth - 16);
  const top = box.bottom + 18 + pop.offsetHeight < window.innerHeight ? box.bottom + 18 : Math.max(16, box.top - pop.offsetHeight - 18);
  pop.style.left = `${left}px`; pop.style.top = `${top}px`;
}
function showStep(index) {
  current = Math.max(0, Math.min(index, steps.length - 1));
  document.querySelectorAll('.tour-target').forEach(el => el.classList.remove('is-highlighted'));
  const step = steps[current]; const target = $(step.target);
  $('tour-step').textContent = current + 1; $('tour-title').textContent = step.title; $('tour-copy').textContent = step.copy;
  $('tour-back').style.visibility = current ? 'visible' : 'hidden'; $('tour-next').innerHTML = current === steps.length - 1 ? 'Done <span>✓</span>' : 'Next <span>→</span>';
  target.classList.add('is-highlighted'); target.scrollIntoView({ behavior: 'smooth', block: 'center' });
  setTimeout(() => positionPopover(target), 220);
}
function closeTour() { $('tour-backdrop').hidden = true; $('tour-popover').hidden = true; document.querySelectorAll('.tour-target').forEach(el => el.classList.remove('is-highlighted')); }
function openTour() { $('tour-backdrop').hidden = false; $('tour-popover').hidden = false; showStep(0); }
document.addEventListener('DOMContentLoaded', () => {
  $('start-tour').addEventListener('click', openTour); $('hero-tour').addEventListener('click', openTour); $('close-tour').addEventListener('click', closeTour);
  $('tour-next').addEventListener('click', () => current === steps.length - 1 ? closeTour() : showStep(current + 1)); $('tour-back').addEventListener('click', () => showStep(current - 1)); $('tour-backdrop').addEventListener('click', closeTour);
  window.addEventListener('resize', () => { if (!$('tour-popover').hidden) positionPopover($(steps[current].target)); });
});
