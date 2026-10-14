function toggleMenu(){document.querySelector('.nav-links').classList.toggle('open')}
function searchPage(){const q=document.getElementById('globalSearch').value.toLowerCase();if(q.includes('center'))location.href='live-centers.html';else if(q.includes('queue'))location.href='queue-management.html';else if(q.includes('slot'))location.href='slot-management.html';else if(q.includes('report'))location.href='reports.html';else if(q.includes('notification'))location.href='notifications.html';else location.href='dashboard.html'}
document.querySelectorAll('[data-year]').forEach(e=>e.textContent=new Date().getFullYear());
function openModal(title,body){const b=document.getElementById('modalBackdrop');if(!b)return;document.getElementById('modalTitle').textContent=title;document.getElementById('modalBody').innerHTML=body;b.classList.add('show')}
function closeModal(){const b=document.getElementById('modalBackdrop');if(b)b.classList.remove('show')}
