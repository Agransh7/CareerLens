import * as pdfjsLib from 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.4.168/pdf.min.mjs';

const form = document.querySelector('#tailorForm');
const companyInput = document.querySelector('#company');
const fileInput = document.querySelector('#resumeFile');
const fileLabel = document.querySelector('#fileLabel');
const fileMeta = document.querySelector('#fileMeta');
const dropzone = document.querySelector('#dropzone');
const errorMessage = document.querySelector('#errorMessage');
const submitButton = document.querySelector('#submitButton');
const resultSection = document.querySelector('#resultSection');
const resultText = document.querySelector('#resultText');
let selectedFile = null;
let generatedMarkdown = '';

for (const chip of document.querySelectorAll('.company-chip')) {
  chip.addEventListener('click', () => {
    companyInput.value = chip.dataset.company;
    document.querySelectorAll('.company-chip').forEach((item) => item.classList.toggle('selected', item === chip));
  });
}
companyInput.addEventListener('input', () => document.querySelectorAll('.company-chip').forEach((chip) => chip.classList.toggle('selected', chip.dataset.company.toLowerCase() === companyInput.value.trim().toLowerCase())));

function setFile(file) {
  selectedFile = file || null;
  if (!selectedFile) {
    fileLabel.innerHTML = 'Drop your resume here, or <span>browse</span>';
    fileMeta.textContent = 'Your details stay on this device except for the text sent to Gemini.';
    return;
  }
  fileLabel.textContent = selectedFile.name;
  fileMeta.textContent = `${(selectedFile.size / 1024 / 1024).toFixed(2)} MB · Ready to read`;
  errorMessage.hidden = true;
}

fileInput.addEventListener('change', () => setFile(fileInput.files[0]));
for (const eventName of ['dragenter', 'dragover']) dropzone.addEventListener(eventName, (event) => { event.preventDefault(); dropzone.classList.add('dragging'); });
for (const eventName of ['dragleave', 'drop']) dropzone.addEventListener(eventName, (event) => { event.preventDefault(); dropzone.classList.remove('dragging'); });
dropzone.addEventListener('drop', (event) => { const file = event.dataTransfer.files[0]; if (file) setFile(file); });

async function extractDocx(arrayBuffer) {
  const JSZip = (await import('https://cdn.jsdelivr.net/npm/jszip@3.10.1/+esm')).default;
  const archive = await JSZip.loadAsync(arrayBuffer);
  const documentFile = archive.file('word/document.xml');
  if (!documentFile) throw new Error('Could not read the text from this DOCX. Try saving it as PDF or TXT.');
  const xml = await documentFile.async('string');
  const doc = new DOMParser().parseFromString(xml, 'application/xml');
  return [...doc.getElementsByTagName('w:p')].map((p) => [...p.getElementsByTagName('w:t')].map((node) => node.textContent).join('')).join('\n');
}

async function readResume(file) {
  const name = file.name.toLowerCase();
  if (name.endsWith('.txt')) return await file.text();
  if (name.endsWith('.pdf')) {
    pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.4.168/pdf.worker.min.mjs';
    const pdf = await pdfjsLib.getDocument({ data: await file.arrayBuffer() }).promise;
    const lines = [];
    for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
      const page = await pdf.getPage(pageNumber);
      const content = await page.getTextContent();
      lines.push(content.items.map((item) => item.str || '').join(' '));
    }
    const text = lines.join('\n').trim();
    if (text.length < 30) throw new Error('This PDF may be scanned or image-only. Please use a text based PDF or upload a TXT file.');
    return text;
  }
  if (name.endsWith('.docx')) return await extractDocx(await file.arrayBuffer());
  throw new Error('Please choose a PDF, DOCX, or TXT file.');
}

function inlineMarkdown(value) {
  return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/\*(.+?)\*/g, '<em>$1</em>').replace(/`([^`]+)`/g, '<code>$1</code>');
}

function renderMarkdown(markdown) {
  const lines = markdown.split(/\r?\n/);
  const output = [];
  let inList = false;
  for (const line of lines) {
    const heading = line.match(/^(#{1,3})\s+(.+)/);
    const list = line.match(/^\s*[-*]\s+(.+)/);
    if (list) {
      if (!inList) { output.push('<ul>'); inList = true; }
      output.push(`<li>${inlineMarkdown(list[1])}</li>`);
      continue;
    }
    if (inList) { output.push('</ul>'); inList = false; }
    if (heading) output.push(`<h${heading[1].length}>${inlineMarkdown(heading[2])}</h${heading[1].length}>`);
    else if (line.trim()) output.push(`<p>${inlineMarkdown(line)}</p>`);
  }
  if (inList) output.push('</ul>');
  return output.join('');
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  errorMessage.hidden = true;
  if (!companyInput.value.trim()) { errorMessage.textContent = 'Add the company you are applying to.'; errorMessage.hidden = false; companyInput.focus(); return; }
  if (!selectedFile) { errorMessage.textContent = 'Upload a resume to get started.'; errorMessage.hidden = false; return; }
  if (selectedFile.size > 5 * 1024 * 1024) { errorMessage.textContent = 'This file is over 5 MB. Choose a smaller resume file.'; errorMessage.hidden = false; return; }
  submitButton.disabled = true;
  submitButton.querySelector('span').textContent = 'Reading your resume…';
  try {
    const resume = (await readResume(selectedFile)).trim();
    if (resume.length < 40) throw new Error('There is not enough readable text in this file. Please check the file and try again.');
    submitButton.querySelector('span').textContent = 'Finding the right words…';
    const response = await fetch('/api/tailor', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ company: companyInput.value.trim(), role: document.querySelector('#role').value.trim(), jobDescription: document.querySelector('#jobDescription').value.trim(), resume }) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not tailor the resume. Please try again.');
    generatedMarkdown = result.resume;
    resultText.innerHTML = renderMarkdown(generatedMarkdown);
    document.querySelector('#resultCompany').textContent = companyInput.value.trim();
    resultSection.hidden = false;
    resultSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (error) {
    errorMessage.textContent = error.message || 'Something went wrong. Please try again.';
    errorMessage.hidden = false;
  } finally {
    submitButton.disabled = false;
    submitButton.querySelector('span').textContent = 'Tailor my resume';
  }
});

document.querySelector('#downloadButton').addEventListener('click', () => {
  const blob = new Blob([generatedMarkdown], { type: 'text/markdown;charset=utf-8' });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = `CareerLens-${companyInput.value.trim().replace(/[^a-z0-9]+/gi, '-')}-resume.md`;
  link.click();
  URL.revokeObjectURL(link.href);
});
document.querySelector('#copyButton').addEventListener('click', async (event) => {
  await navigator.clipboard.writeText(generatedMarkdown);
  event.currentTarget.textContent = 'Copied';
  setTimeout(() => { event.currentTarget.textContent = 'Copy text'; }, 1600);
});

const infoDialog = document.querySelector('#infoDialog');
document.querySelector('#privacyInfo').addEventListener('click', () => infoDialog.showModal());
document.querySelector('#helpButton').addEventListener('click', () => infoDialog.showModal());
document.querySelector('#closeDialog').addEventListener('click', () => infoDialog.close());
