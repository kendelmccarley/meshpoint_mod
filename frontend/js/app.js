/**
 * Simple single-page controller for the local Mesh Point dashboard.
 * Wires up map, node list, packet feed, and WebSocket.
 */
document.addEventListener('DOMContentLoaded', async () => {
    const nodeMap = new NodeMap('map');
    const nodeList = new SimpleNodeList('node-list');
    const packetFeed = new SimplePacketFeed('packet-tbody');

    await _loadInitial(nodeMap, nodeList, packetFeed);

    window.concentratorWS.on('packet', (packet) => {
        packetFeed.addPacket(packet);
        nodeMap.updateFromPacket(packet);
        nodeList.updateFromPacket(packet);
        _incrementPacketCount();
        _setText('stat-nodes', `${nodeList.nodeCount} nodes`);
    });

    window.concentratorWS.connect();

    setInterval(() => _refreshData(nodeMap, nodeList), 15_000);
});

async function _loadInitial(nodeMap, nodeList, packetFeed) {
    try {
        const [deviceRes, nodesRes, packetsRes] = await Promise.all([
            fetch('/api/device/status'),
            fetch('/api/nodes'),
            fetch('/api/packets?limit=50'),
        ]);
        const device = await deviceRes.json();
        const nodesData = await nodesRes.json();
        const packetsData = await packetsRes.json();

        _setText('device-name', device.device_name || 'Mesh Point');
        _setText('device-version', device.firmware_version ? `v${device.firmware_version}` : '');

        const nodes = nodesData.nodes || nodesData || [];
        nodeMap.loadNodes(nodes, device);
        nodeList.loadNodes(nodes);
        _setText('stat-nodes', `${nodes.length} nodes`);

        const packets = packetsData.packets || packetsData || [];
        const sorted = packets.sort((a, b) => {
            const aTime = a.rx_time || new Date(a.timestamp || 0).getTime() / 1000;
            const bTime = b.rx_time || new Date(b.timestamp || 0).getTime() / 1000;
            return aTime - bTime;
        });
        sorted.forEach(pkt => packetFeed.addPacket(pkt));
        _totalPackets = sorted.length;
        _setText('stat-packets', `${_totalPackets} packets`);
    } catch (e) {
        console.error('Initial load failed:', e);
    }
}

async function _refreshData(nodeMap, nodeList) {
    try {
        const res = await fetch('/api/nodes');
        const data = await res.json();
        const nodes = data.nodes || data || [];
        nodeMap.loadNodes(nodes);
        nodeList.loadNodes(nodes);
        _setText('stat-nodes', `${nodes.length} nodes`);
    } catch (e) {
        console.error('Refresh failed:', e);
    }
}

let _totalPackets = 0;

function _incrementPacketCount() {
    _totalPackets++;
    _setText('stat-packets', `${_totalPackets} packets`);
}

function _setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
}
