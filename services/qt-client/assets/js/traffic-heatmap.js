import { getMapConfig } from './map-config-loader.js';

function logToPython(message) {
    if (window.globalChannel && window.globalChannel.objects.logger_bridge) {
        window.globalChannel.objects.logger_bridge.log_info(message);
    } else {
        console.log(message);
    }
}

export class TrafficHeatmap {
    constructor(map) {
        this.map = map;
        this.ws = null;
        this.loggedOnce = false;
        
        const config = getMapConfig();
        const visualizationModes = (config && config.visualizationModes) || ['highway_type'];
        this.isHeatmapEnabled = visualizationModes.includes('traffic_load');

        if (this.isHeatmapEnabled) {
            this.initWebSocket();
        } else {
            logToPython("[Heatmap] Disabled by visualization_modes. Telemetry will not be started.");
        }
    }

    initWebSocket() {
        const config = getMapConfig();
        const baseUrl = (config && config.apiBaseUrl) || 'http://localhost:8000';
        const wsBase = baseUrl.replace(/^http/, 'ws');
        const wsUrl = `${wsBase}/ws/sim_telemetry`;
        
        logToPython(`[Heatmap] Connecting to ${wsUrl}...`);
        this.ws = new WebSocket(wsUrl);
        
        this.ws.onopen = () => {
            logToPython(`[Heatmap] WS Connected successfully to ${wsUrl}`);
        };
        
        this.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                this.updateHeatmap(data);
            } catch (e) {
                logToPython(`[Heatmap] JSON parse error: ${e.message}`);
            }
        };

        this.ws.onerror = (error) => {
            logToPython(`[Heatmap] WS Error: ${error}`);
        };

        this.ws.onclose = () => {
            logToPython("[Heatmap] WS closed. Reconnecting in 3s...");
            setTimeout(() => this.initWebSocket(), 3000);
        };
    }

    updateHeatmap(data) {
        if (!this.map.isStyleLoaded()) return;

        // Clear old states - disabled to prevent flickering/holey map
        // this.map.removeFeatureState({ source: 'graph-vector', sourceLayer: 'ways' });

        if (!this.loggedOnce && data.length > 0) {
            logToPython(`[Heatmap] First update applied to ${data.length} active edges. Sample OSM ID: ${data[0].id}, Vol: ${data[0].v}, Cap: ${data[0].c}`);
            
            // Query a feature to see if it has an ID
            const features = this.map.querySourceFeatures('graph-vector', { sourceLayer: 'ways' });
            if (features && features.length > 0) {
                logToPython(`[Heatmap Debug] Found ${features.length} features in source. Sample feature ID: ${features[0].id}. Sample properties: ${JSON.stringify(features[0].properties)}`);
                
                // Let's manually set state and get it to see if it works
                this.map.setFeatureState(
                    { source: 'graph-vector', sourceLayer: 'ways', id: features[0].id },
                    { volume: 50, capacity: 100 }
                );
                const state = this.map.getFeatureState({ source: 'graph-vector', sourceLayer: 'ways', id: features[0].id });
                logToPython(`[Heatmap Debug] Tested feature state for ${features[0].id}: ${JSON.stringify(state)}`);
            } else {
                logToPython(`[Heatmap Debug] No features found in graph-vector source layer ways!`);
            }
            
            this.loggedOnce = true;
        }

        // Apply new states using OSM ID!
        for (const item of data) {
            this.map.setFeatureState(
                { source: 'graph-vector', sourceLayer: 'ways', id: item.id },
                { volume: item.v, capacity: item.c }
            );
        }
    }
}
