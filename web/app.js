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
let selectedFile = null;
let generatedMarkdown = '';
let originalResumeText = '';
let currentSuggestions = [];
let learningNotesStorageKey = '';

const themeToggle = document.querySelector('#themeToggle');
const savedTheme = localStorage.getItem('careerlens-theme') || 'dark';
document.body.dataset.theme = savedTheme;
themeToggle.textContent = savedTheme === 'dark' ? 'Light theme' : 'Dark theme';
themeToggle.addEventListener('click', () => {
  const nextTheme = document.body.dataset.theme === 'dark' ? 'light' : 'dark';
  document.body.dataset.theme = nextTheme;
  localStorage.setItem('careerlens-theme', nextTheme);
  themeToggle.textContent = nextTheme === 'dark' ? 'Light theme' : 'Dark theme';
});

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
    fileMeta.textContent = 'PDF, DOCX, or TXT';
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

function escapeHtml(value) {
  return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function renderRequirements(requirements) {
  const container = document.querySelector('#requirementMap');
  container.replaceChildren();
  if (!requirements.length) {
    container.innerHTML = '<p class="empty-state">No clear requirements were found. Add a job description and try again.</p>';
    return;
  }
  for (const item of requirements) {
    const card = document.createElement('article');
    card.className = `requirement-card status-${item.status}`;
    const statusLabel = item.status === 'covered' ? 'Evidence found' : item.status === 'partial' ? 'Some evidence' : item.status === 'unverified' ? 'Quote not verified' : 'Gap';
    card.innerHTML = `<div class="requirement-top"><h4>${escapeHtml(item.requirement)}</h4><span class="status-badge">${statusLabel}</span></div><p>${escapeHtml(item.reason || '')}</p>`;
    if (item.evidence_quote) {
      const quoteLabel = document.createElement('div');
      quoteLabel.className = 'evidence-label';
      quoteLabel.textContent = item.grounded ? 'RESUME EVIDENCE' : 'UNVERIFIED QUOTE';
      const quote = document.createElement('blockquote');
      quote.textContent = item.evidence_quote;
      card.append(quoteLabel, quote);
    }
    container.append(card);
  }
}

function renderExperienceReviews(reviews) {
  const container = document.querySelector('#experienceReviewList');
  container.replaceChildren();
  if (!reviews.length) {
    container.innerHTML = '<p class="empty-state">No work, internship, project, research, or similar experience entry could be verified in the resume.</p>';
    return;
  }
  for (const item of reviews) {
    const dimensions = item.impact_dimensions || {};
    const completeImpact = ['effect', 'scale', 'beneficiary'].every((key) => dimensions[key]?.grounded);
    const anyImpact = ['effect', 'scale', 'beneficiary'].some((key) => dimensions[key]?.grounded);
    const card = document.createElement('article');
    card.className = `experience-review-card ${completeImpact ? 'impact-found' : 'impact-missing'}`;
    const header = document.createElement('div');
    header.className = 'experience-review-header';
    const type = document.createElement('span');
    type.className = 'experience-type';
    type.textContent = item.experience_type;
    const status = document.createElement('span');
    status.className = 'impact-status';
    status.textContent = completeImpact ? 'Impact well described' : anyImpact ? 'Add impact detail' : 'Add the result';
    header.append(type, status);
    const sourceLabel = document.createElement('div');
    sourceLabel.className = 'evidence-label';
    sourceLabel.textContent = 'EXPERIENCE FROM YOUR RESUME';
    const source = document.createElement('blockquote');
    source.textContent = item.source_quote;
    card.append(header, sourceLabel, source);
    const dimensionList = document.createElement('div');
    dimensionList.className = 'impact-dimensions';
    const dimensionLabels = { effect: 'Effect', scale: 'Scale / how much', beneficiary: 'Who benefited' };
    for (const [key, label] of Object.entries(dimensionLabels)) {
      const row = document.createElement('div');
      row.className = `impact-dimension ${dimensions[key]?.grounded ? 'present' : 'missing'}`;
      const name = document.createElement('strong');
      name.textContent = label;
      const evidence = document.createElement('span');
      evidence.textContent = dimensions[key]?.grounded ? dimensions[key].quote : 'Not stated in this resume entry';
      row.append(name, evidence);
      dimensionList.append(row);
    }
    card.append(dimensionList);
    if (item.impact_summary) {
      const summary = document.createElement('p');
      summary.className = 'impact-summary';
      summary.textContent = item.impact_summary;
      card.append(summary);
    }
    if (!completeImpact) {
      const question = document.createElement('div');
      question.className = 'impact-question';
      question.innerHTML = `<strong>Ask yourself</strong><p>${escapeHtml(item.follow_up_question)}</p>`;
      card.append(question);
    }
    container.append(card);
  }
}

function renderSuggestions(suggestions) {
  const container = document.querySelector('#suggestionList');
  container.replaceChildren();
  currentSuggestions = suggestions.map((item) => ({ ...item, included: false }));
  if (!currentSuggestions.length) {
    container.innerHTML = '<p class="empty-state">No resume lines could be matched safely to these requirements. You can still use the evidence gaps above to guide what to add.</p>';
    updatePreview();
    return;
  }
  currentSuggestions.forEach((item, index) => {
    const card = document.createElement('article');
    card.className = `suggestion-card ${item.grounded ? '' : 'unverified'}`;
    const title = document.createElement('div');
    title.className = 'suggestion-title';
    title.innerHTML = `<span class="suggestion-index">${String(index + 1).padStart(2, '0')}</span><h4>${escapeHtml(item.requirement)}</h4>`;
    card.append(title);

    const evidenceLabel = document.createElement('div');
    evidenceLabel.className = 'evidence-label';
    evidenceLabel.textContent = item.grounded ? 'FROM YOUR RESUME' : 'SOURCE QUOTE NOT FOUND';
    const source = document.createElement('blockquote');
    source.className = 'source-quote';
    source.textContent = item.source_quote || 'No source quote was provided.';
    const rewriteLabel = document.createElement('label');
    rewriteLabel.className = 'evidence-label rewrite-label';
    rewriteLabel.textContent = 'SUGGESTED REWRITE';
    const rewrite = document.createElement('textarea');
    rewrite.className = 'rewrite-input';
    rewrite.rows = 3;
    rewrite.maxLength = 1500;
    rewrite.value = item.rewrite;
    rewrite.disabled = !item.grounded;
    rewrite.addEventListener('input', () => { item.rewrite = rewrite.value; updatePreview(); });
    const reason = document.createElement('p');
    reason.className = 'suggestion-reason';
    reason.textContent = item.reason;
    const interview = document.createElement('div');
    interview.className = 'interview-check';
    interview.innerHTML = `<strong>Interview check</strong><p>${escapeHtml(item.interview_question)}</p>`;
    const confirmLabel = document.createElement('label');
    confirmLabel.className = 'confirm-label';
    const confirm = document.createElement('input');
    confirm.type = 'checkbox';
    confirm.checked = item.needs_confirmation;
    confirm.addEventListener('change', () => { item.needs_confirmation = confirm.checked; updatePreview(); });
    confirmLabel.append(confirm, document.createTextNode(' I still need to confirm this detail'));
    const addButton = document.createElement('button');
    addButton.type = 'button';
    addButton.className = 'keep-button';
    addButton.disabled = !item.grounded;
    addButton.textContent = 'Add to preview';
    addButton.addEventListener('click', () => {
      item.included = !item.included;
      addButton.textContent = item.included ? 'Remove from preview' : 'Add to preview';
      addButton.classList.toggle('included', item.included);
      updatePreview();
    });
    card.append(evidenceLabel, source, rewriteLabel, rewrite, reason, interview, confirmLabel, addButton);
    container.append(card);
  });
  updatePreview();
}

function renderTechnicalLearningNotes(notes, jobDescription) {
  const container = document.querySelector('#technicalGapList');
  container.replaceChildren();
  if (!notes.length) {
    container.innerHTML = '<p class="empty-state">No technical learning requirements were identified for this role.</p>';
  } else {
    for (const item of notes) {
      const card = document.createElement('article');
      card.className = 'technical-gap-card';
      const skill = document.createElement('h4');
      skill.textContent = item.skill;
      const quoteLabel = document.createElement('div');
      quoteLabel.className = 'evidence-label';
      quoteLabel.textContent = item.source_label || (jobDescription.trim() ? 'FROM THE JOB DESCRIPTION' : 'ROLE-BASED REQUIREMENT');
      const quote = document.createElement('blockquote');
      quote.textContent = item.job_quote || 'This technical skill is not mentioned in the resume and has been added as a learning requirement.';
      const reason = document.createElement('p');
      reason.textContent = item.why_it_matters;
      const practice = document.createElement('p');
      practice.className = 'practice-step';
      practice.innerHTML = `<strong>Try this:</strong> ${escapeHtml(item.practice_step)}`;
      card.append(skill, quoteLabel, quote, reason, practice);
      container.append(card);
    }
  }

  const keySource = `${companyInput.value.trim()}|${document.querySelector('#role').value.trim()}|${jobDescription.trim()}`.toLocaleLowerCase();
  let hash = 2166136261;
  for (let index = 0; index < keySource.length; index += 1) hash = Math.imul(hash ^ keySource.charCodeAt(index), 16777619);
  learningNotesStorageKey = `careerlens-learning-${hash >>> 0}`;
  const defaultNotes = notes.map((item) => `${item.skill}\nWhy it matters: ${item.why_it_matters}\nPractice: ${item.practice_step}`).join('\n\n');
  let savedNotes = '';
  try { savedNotes = localStorage.getItem(learningNotesStorageKey) || ''; } catch {}
  document.querySelector('#learningNotes').value = savedNotes || defaultNotes;
  document.querySelector('#notesSavedStatus').textContent = savedNotes ? 'Saved in this browser' : '';
}

function replaceSourceExcerpt(text, quote, replacement) {
  if (!quote.trim()) return text;
  const pattern = quote.trim().split(/\s+/).map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('\\s+');
  return text.replace(new RegExp(pattern, 'i'), replacement);
}

function updatePreview() {
  let preview = originalResumeText;
  for (const item of currentSuggestions) {
    if (item.included && item.grounded) preview = replaceSourceExcerpt(preview, item.source_quote, item.rewrite);
  }
  generatedMarkdown = preview;
  const previewElement = document.querySelector('#resumePreview');
  if (previewElement) previewElement.textContent = preview || 'Your resume preview will appear here.';
  const accepted = currentSuggestions.filter((item) => item.included && item.grounded).length;
  const warning = currentSuggestions.filter((item) => item.included && item.needs_confirmation).length;
  const status = document.querySelector('#previewStatus');
  if (status) status.textContent = warning
    ? `${accepted} suggestion${accepted === 1 ? '' : 's'} added · confirm ${warning} detail${warning === 1 ? '' : 's'} before copying or downloading.`
    : `${accepted} suggestion${accepted === 1 ? '' : 's'} added.`;
  document.querySelector('#copyButton').disabled = warning > 0;
  document.querySelector('#downloadDocxButton').disabled = warning > 0;
  document.querySelector('#downloadPdfButton').disabled = warning > 0;
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  errorMessage.hidden = true;
  if (!companyInput.value.trim()) { errorMessage.textContent = 'Add the company you are applying to.'; errorMessage.hidden = false; companyInput.focus(); return; }
  if (!selectedFile) { errorMessage.textContent = 'Upload a resume to get started.'; errorMessage.hidden = false; return; }
  if (!document.querySelector('#role').value.trim() && !document.querySelector('#jobDescription').value.trim()) { errorMessage.textContent = 'Add a target role or job description to build a useful evidence map.'; errorMessage.hidden = false; document.querySelector('#role').focus(); return; }
  if (selectedFile.size > 5 * 1024 * 1024) { errorMessage.textContent = 'This file is over 5 MB. Choose a smaller resume file.'; errorMessage.hidden = false; return; }
  submitButton.disabled = true;
  submitButton.querySelector('span').textContent = 'Reading your resume…';
  try {
    originalResumeText = (await readResume(selectedFile)).trim();
    if (originalResumeText.length < 40) throw new Error('There is not enough readable text in this file. Please check the file and try again.');
    submitButton.querySelector('span').textContent = 'Finding the right words…';
    const response = await fetch('/api/tailor', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ company: companyInput.value.trim(), role: document.querySelector('#role').value.trim(), jobDescription: document.querySelector('#jobDescription').value.trim(), resume: originalResumeText }) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not tailor the resume. Please try again.');
    renderRequirements(result.requirements || []);
    renderExperienceReviews(result.experience_reviews || []);
    renderSuggestions(result.suggestions || []);
    const effectiveJobDescription = result.job_posting?.job_description || document.querySelector('#jobDescription').value;
    renderTechnicalLearningNotes(result.technical_learning_notes || [], effectiveJobDescription);
    document.querySelector('#resultCompany').textContent = companyInput.value.trim();
    document.querySelector('#modelUsed').textContent = result.model ? ` · ${result.model}` : '';
    const jobMatch = document.querySelector('#jobMatch');
    if (result.job_posting) {
      const jobMatchLink = document.querySelector('#jobMatchLink');
      document.querySelector('#jobMatchLabel').textContent = 'Matching public listing:';
      jobMatchLink.textContent = result.job_posting.title;
      jobMatchLink.href = result.job_posting.source_url;
      jobMatchLink.hidden = false;
      document.querySelector('#jobMatchSource').textContent = `Source: ${result.job_posting.source_title}`;
      jobMatch.hidden = false;
    } else {
      jobMatch.hidden = true;
    }
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

async function downloadResume(format) {
  const button = document.querySelector(format === 'docx' ? '#downloadDocxButton' : '#downloadPdfButton');
  const originalLabel = button.textContent;
  button.disabled = true;
  button.textContent = 'Creating…';
  try {
    const response = await fetch('/api/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ resume: generatedMarkdown, format }),
    });
    if (!response.ok) {
      const issue = await response.json().catch(() => ({}));
      throw new Error(issue.error || 'Could not create the resume file. Try again.');
    }
    const blob = await response.blob();
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    const companySlug = companyInput.value.trim().replace(/[^a-z0-9]+/gi, '-') || 'company';
    link.download = `CareerLens-${companySlug}-resume.${format}`;
    link.click();
    URL.revokeObjectURL(link.href);
  } catch (error) {
    document.querySelector('#emailDraftStatus').textContent = error.message;
  } finally {
    button.textContent = originalLabel;
    button.disabled = currentSuggestions.some((item) => item.included && item.needs_confirmation);
  }
}
document.querySelector('#downloadDocxButton').addEventListener('click', () => downloadResume('docx'));
document.querySelector('#downloadPdfButton').addEventListener('click', () => downloadResume('pdf'));
document.querySelector('#openGmailDraft').addEventListener('click', () => {
  const recipient = document.querySelector('#companyEmail');
  const status = document.querySelector('#emailDraftStatus');
  status.textContent = '';
  if (!generatedMarkdown.trim()) {
    status.textContent = 'Generate your resume preview before opening an email draft.';
    return;
  }
  if (!recipient.value.trim() || !recipient.checkValidity()) {
    status.textContent = 'Enter a valid recruiter or company email address.';
    recipient.focus();
    return;
  }
  const role = document.querySelector('#role').value.trim();
  const company = companyInput.value.trim();
  const subject = `Application${role ? `: ${role}` : ''} at ${company}`;
  const body = `Hello,\n\nI am applying${role ? ` for the ${role} role` : ''} at ${company}. Please find my resume attached.\n\nRegards,\n${generatedMarkdown.split(/\r?\n/).find((line) => line.trim()) || ''}`;
  const params = new URLSearchParams({ view: 'cm', fs: '1', to: recipient.value.trim(), su: subject, body });
  window.open(`https://mail.google.com/mail/?${params.toString()}`, '_blank', 'noopener,noreferrer');
  status.textContent = 'Gmail draft opened. Attach the downloaded PDF or DOCX, then review and send it.';
});
document.querySelector('#copyButton').addEventListener('click', async (event) => {
  await navigator.clipboard.writeText(generatedMarkdown);
  event.currentTarget.textContent = 'Copied';
  setTimeout(() => { event.currentTarget.textContent = 'Copy text'; }, 1600);
});
document.querySelector('#saveLearningNotes').addEventListener('click', () => {
  try {
    localStorage.setItem(learningNotesStorageKey, document.querySelector('#learningNotes').value);
    document.querySelector('#notesSavedStatus').textContent = 'Saved in this browser';
  } catch {
    document.querySelector('#notesSavedStatus').textContent = 'Could not save notes in this browser';
  }
});
document.querySelector('#learningNotes').addEventListener('input', () => {
  document.querySelector('#notesSavedStatus').textContent = 'Unsaved changes';
});

