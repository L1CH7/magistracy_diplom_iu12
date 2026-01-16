import React, { useEffect, useRef, useState } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';

export default function Map() {
    const mapContainer = useRef(null);
    const map = useRef(null);
    const [zoom] = useState(12);
    const [center] = useState([37.6173, 55.7558]); // Moscow

    useEffect(() => {
        if (map.current) return;

        map.current = new maplibregl.Map({
            container: mapContainer.current,
            style: {
                version: 8,
                sources: {
                    'osm-tiles': {
                        type: 'vector',
                        tiles: [
                            // Point to our Gateway service
                            `${window.location.origin}/tiles/{z}/{x}/{y}.mvt`
                        ],
                    }
                },
                layers: [
                    {
                        id: 'roads',
                        type: 'line',
                        source: 'osm-tiles',
                        'source-layer': 'roads', // Layer name from ST_AsMVT
                        paint: {
                            'line-color': '#ff0000',
                            'line-width': 2
                        }
                    }
                ]
            },
            center: center,
            zoom: zoom
        });

        map.current.addControl(new maplibregl.NavigationControl(), 'top-right');
    }, [center, zoom]);

    return (
        <div style={{ width: '100%', height: '100%' }} ref={mapContainer} />
    );
}
