/**
 * Main messaging panel controller for the local Mesh Point dashboard.
 * Manages the two-column layout (sidebar + chat), tab switching,
 * protocol filtering, WebSocket event routing, and send orchestration.
 */
class MessagingPanel {
    constructor() {
        this._initialized = false;
        this._contacts = null;
        this._chat = null;
        this._activeConvo = null;
        this._unreadTotal = 0;
    }

    init() {
        if (this._initialized) return;
        this._initialized = true;

        const panel = document.getElementById('messaging-panel');
        if (!panel) return;

        panel.innerHTML = `
            <div class="messaging">
                <div class="msg-sidebar">
                    <div class="msg-sidebar__header">
                        <span class="msg-sidebar__title">Messages</span>
                        <button class="msg-sidebar__new-btn" id="msg-new-btn">+ New</button>
                    </div>
                    <div class="msg-protocol-toggle">
                        <button class="msg-protocol-toggle__btn msg-protocol-toggle__btn--active" data-filter="all">All</button>
                        <button class="msg-protocol-toggle__btn" data-filter="meshtastic">MT</button>
                        <button class="msg-protocol-toggle__btn" data-filter="meshcore">MC</button>
                    </div>
                    <div class="msg-sidebar__list" id="msg-convo-list"></div>
                </div>
                <div class="msg-chat" id="msg-chat-area"></div>
            </div>
        `;

        const listEl = document.getElementById('msg-convo-list');
        const chatEl = document.getElementById('msg-chat-area');

        this._contacts = new MessagingContacts(listEl, (convo) => this._onConversationSelected(convo));
        this._chat = new MessagingChat(chatEl, (text, convo) => this._onSendMessage(text, convo));

        document.getElementById('msg-new-btn').addEventListener('click', () => {
            this._contacts.openContactPicker();
        });

        panel.querySelectorAll('.msg-protocol-toggle__btn').forEach(btn => {
            btn.addEventListener('click', () => {
                panel.querySelectorAll('.msg-protocol-toggle__btn').forEach(b => b.classList.remove('msg-protocol-toggle__btn--active'));
                btn.classList.add('msg-protocol-toggle__btn--active');
                this._contacts.setFilter(btn.dataset.filter);
            });
        });

        this._setupWebSocket();
        this._contacts.load();
        this._loadStatus();
    }

    onActivated() {
        if (!this._initialized) this.init();
        this._contacts.load();
    }

    _onConversationSelected(convo) {
        this._activeConvo = convo;
        this._chat.setConversation(convo);
        this._contacts.setActive(convo.node_id);
    }

    async _onSendMessage(text, convo) {
        const isBroadcast = convo.is_broadcast || (convo.node_id || '').startsWith('broadcast:');
        const destination = isBroadcast ? 'broadcast' : convo.node_id;

        const tempMsg = this._chat.addOptimisticMessage(text, convo.protocol);

        try {
            const res = await fetch('/api/messages/send', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    text: text,
                    destination: destination,
                    protocol: convo.protocol || 'meshtastic',
                    channel: convo.channel || 0,
                }),
            });
            const result = await res.json();

            if (result.success) {
                this._chat.updateMessageStatus(tempMsg.id, 'sent', result.packet_id);
                this._contacts.addOrUpdateConversation({
                    node_id: convo.node_id,
                    node_name: convo.node_name,
                    protocol: convo.protocol,
                    text: text,
                    direction: 'sent',
                    timestamp: new Date().toISOString(),
                });
            } else {
                this._chat.updateMessageStatus(tempMsg.id, `failed: ${result.error}`, '');
            }
        } catch (e) {
            console.error('Send failed:', e);
            this._chat.updateMessageStatus(tempMsg.id, 'error', '');
        }
    }

    _setupWebSocket() {
        window.concentratorWS.on('message_received', (data) => {
            if (this._activeConvo && data.node_id === this._activeConvo.node_id) {
                this._chat.addMessage({
                    id: Date.now(),
                    direction: 'received',
                    text: data.text,
                    node_id: data.node_id,
                    node_name: data.node_name || '',
                    protocol: data.protocol || 'meshtastic',
                    channel: 0,
                    timestamp: new Date().toISOString(),
                    status: 'delivered',
                    packet_id: data.packet_id || '',
                });
            }
            this._contacts.addOrUpdateConversation(data);
            this._updateUnreadBadge();
        });

        window.concentratorWS.on('message_sent', (data) => {
            this._contacts.addOrUpdateConversation({
                ...data,
                direction: 'sent',
            });
        });
    }

    async _loadStatus() {
        try {
            const res = await fetch('/api/messages/status');
            const status = await res.json();
            const mt = status.meshtastic || {};
            const mc = status.meshcore || {};
            console.log(
                `TX status: MT=${mt.enabled ? 'ON' : 'OFF'} (${mt.node_id}), MC=${mc.connected ? 'CONNECTED' : 'OFF'}`
            );
        } catch (e) {
            console.log('TX status unavailable');
        }
    }

    _updateUnreadBadge() {
        const badge = document.getElementById('msg-unread-badge');
        if (!badge) return;
        this._unreadTotal++;
        badge.textContent = this._unreadTotal;
        badge.style.display = this._unreadTotal > 0 ? 'inline-block' : 'none';
    }

    resetUnreadBadge() {
        this._unreadTotal = 0;
        const badge = document.getElementById('msg-unread-badge');
        if (badge) badge.style.display = 'none';
    }
}

window.messagingPanel = new MessagingPanel();
