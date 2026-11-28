// App 外壳的两个本地页面共用：三语文字（跟着手机语言）、保存的服务器地址
var L = (navigator.language || 'en').toLowerCase();
var LANG = L.indexOf('zh') === 0 ? 'zh' : (L.indexOf('sr') === 0 || L.indexOf('hr') === 0 || L.indexOf('bs') === 0) ? 'sr' : 'en';
var TXT = {
  zh: { title: '工作记录系统', addr: '服务器地址', hint: '就是电脑浏览器里打开系统用的地址，例如 192.168.1.60', go: '连接',
        bad: '地址不对：只填 IP 或电脑名，例如 192.168.1.60', fail: '连不上服务器', failHint: '请确认手机连着厂里的 Wi-Fi，服务器地址没有变。',
        retry: '重试', change: '修改服务器地址', now: '现在的地址：' },
  sr: { title: 'Radni dnevnik', addr: 'Adresa servera', hint: 'Ista adresa kao u pregledaču na računaru, npr. 192.168.1.60', go: 'Poveži',
        bad: 'Pogrešna adresa: samo IP ili ime računara, npr. 192.168.1.60', fail: 'Nema veze sa serverom', failHint: 'Proverite da je telefon na fabričkom Wi-Fi-ju i da se adresa servera nije promenila.',
        retry: 'Pokušaj ponovo', change: 'Promeni adresu servera', now: 'Sadašnja adresa: ' },
  en: { title: 'Work Log', addr: 'Server address', hint: 'The same address you open the system with on a computer, e.g. 192.168.1.60', go: 'Connect',
        bad: 'Invalid address: just an IP or computer name, e.g. 192.168.1.60', fail: 'Cannot reach the server', failHint: 'Make sure the phone is on the factory Wi-Fi and the server address has not changed.',
        retry: 'Retry', change: 'Change server address', now: 'Current address: ' },
}[LANG];
function getServer() { try { return localStorage.getItem('server') || ''; } catch (e) { return ''; } }
function setServer(v) { try { localStorage.setItem('server', v); } catch (e) { /* 忽略 */ } }
// 「192.168.1.60」「https://192.168.1.60/」「worklog」都认，只留主机名（可带端口）
function cleanAddr(v) {
  v = (v || '').trim().replace(/^[a-z]+:\/\//i, '').replace(/\/.*$/, '');
  return /^[A-Za-z0-9]([A-Za-z0-9.\-]*[A-Za-z0-9])?(:\d{1,5})?$/.test(v) ? v : '';
}
function openServer(addr) { location.replace('https://' + addr + '/'); }
function fill() {
  document.querySelectorAll('[data-t]').forEach(function (el) { el.textContent = TXT[el.getAttribute('data-t')]; });
  document.title = TXT.title;
}
