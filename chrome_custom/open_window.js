(async () => {
  const url = 'http://127.0.0.1:5000';
  chrome.windows.create({
    url,
    type: 'popup',
    focused: true,
    width: 1400,
    height: 900
  });
})();
