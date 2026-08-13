(function () {
    const HANDOFF_TYPE = 'SCRAPPL_EXTENSION_HANDOFF';
    const STORAGE_KEY = 'scrappl.extension-handoff.v1';
    const TTL_MS = 10 * 60 * 1000;

    function isImageDataUrl(value) {
        return typeof value === 'string' && /^data:image\/[a-z0-9.+-]+;base64,/i.test(value);
    }

    function expectedNonce() {
        return new URLSearchParams(window.location.hash.slice(1)).get('scrappl-handoff');
    }

    function receive(event) {
        const data = event.data;
        if (event.source !== window || event.origin !== window.location.origin || !data ||
            data.type !== HANDOFF_TYPE || typeof data.nonce !== 'string' || !data.nonce ||
            !isImageDataUrl(data.imageDataUrl)) {
            return null;
        }

        const nonce = expectedNonce();
        if (nonce && nonce !== data.nonce) return null;

        const handoff = {
            imageDataUrl: data.imageDataUrl,
            sourceUrl: typeof data.sourceUrl === 'string' ? data.sourceUrl : '',
            title: typeof data.title === 'string' ? data.title : '',
            createdAt: Date.now(),
        };
        sessionStorage.setItem(STORAGE_KEY, JSON.stringify(handoff));
        if (nonce) history.replaceState(null, '', window.location.pathname + window.location.search);
        window.dispatchEvent(new CustomEvent('scrappl:extension-handoff'));
        return handoff;
    }

    function take() {
        const raw = sessionStorage.getItem(STORAGE_KEY);
        sessionStorage.removeItem(STORAGE_KEY);
        if (!raw) return null;
        try {
            const handoff = JSON.parse(raw);
            if (!handoff || !isImageDataUrl(handoff.imageDataUrl) ||
                typeof handoff.createdAt !== 'number' || Date.now() - handoff.createdAt > TTL_MS) {
                return null;
            }
            return {
                imageDataUrl: handoff.imageDataUrl,
                sourceUrl: typeof handoff.sourceUrl === 'string' ? handoff.sourceUrl : '',
                title: typeof handoff.title === 'string' ? handoff.title : '',
                createdAt: handoff.createdAt,
            };
        } catch (error) {
            return null;
        }
    }

    window.addEventListener('message', receive);
    window.ScrapplExtensionHandoff = { receive, take };
})();
