let port = browser.runtime.connectNative("com.nil.browser_control");

port.onMessage.addListener(async (message) => {
    // 1. NAVIGATE
    if (message.action === "navigate") {
        console.log("Navigating to: " + message.url);
        let tabs = await browser.tabs.query({active: true, currentWindow: true});
        if (tabs.length > 0) {
            // Using .catch to prevent the extension from crashing on bad URLs
            browser.tabs.update(tabs[0].id, {url: message.url}).catch(err => {
                console.error("Navigation failed: " + err);
            });
        }
    } 
    
    // 2. RELOAD
    else if (message.action === "reload") {
        let tabs = await browser.tabs.query({active: true, currentWindow: true});
        if (tabs.length > 0) {
            browser.tabs.reload(tabs[0].id);
        }
    } 
    
    // 3. SCREENSHOT (WebP Logic)
    else if (message.action === "screenshot") {
        port.postMessage({action: "status", data: "Capturing..."});
        try {
            let pngDataUrl = await browser.tabs.captureVisibleTab(null, {format: "png"});
            let img = new Image();
            img.onload = () => {
                let canvas = document.createElement('canvas');
                canvas.width = img.width;
                canvas.height = img.height;
                let ctx = canvas.getContext('2d');
                ctx.drawImage(img, 0, 0);

                // Export as WebP to stay under 1MB limit
                let webpDataUrl = canvas.toDataURL("image/webp", 0.8);

                // Double Safety check for 1MB limit
                if (webpDataUrl.length > 1000000) {
                    webpDataUrl = canvas.toDataURL("image/webp", 0.4);
                }

                port.postMessage({
                    action: "screenshot_result",
                    data: webpDataUrl
                });
            };
            img.src = pngDataUrl;
        } catch (error) {
            console.error("Capture failed: " + error);
        }
    }
});
