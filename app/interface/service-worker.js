// service-worker.js - AIter Ego PWA
// Version: 1.0.0

const CACHE_NAME = 'alterego-v1';
const OFFLINE_URL = '/offline.html';

// Fichiers à mettre en cache pour fonctionnement hors-ligne basique
const CACHE_FILES = [
  '/',
  '/offline.html',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png'
];

// Installation du service worker
self.addEventListener('install', (event) => {
  console.log('[SW] Installation...');
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => {
        console.log('[SW] Cache ouvert');
        return cache.addAll(CACHE_FILES);
      })
      .then(() => self.skipWaiting())
  );
});

// Activation et nettoyage des anciens caches
self.addEventListener('activate', (event) => {
  console.log('[SW] Activation...');
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => name !== CACHE_NAME)
          .map((name) => {
            console.log('[SW] Suppression ancien cache:', name);
            return caches.delete(name);
          })
      );
    }).then(() => self.clients.claim())
  );
});

// Stratégie: Network First avec fallback cache
// Les requêtes API vont toujours au réseau, le reste peut être caché
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // API calls - toujours réseau (pas de cache)
  if (url.pathname.startsWith('/send') || 
      url.pathname.startsWith('/health') ||
      url.pathname.startsWith('/transcribe')) {
    event.respondWith(
      fetch(request).catch(() => {
        // Si offline et API, retourner erreur JSON
        return new Response(
          JSON.stringify({ error: 'Hors ligne - connexion requise' }),
          { 
            status: 503,
            headers: { 'Content-Type': 'application/json' }
          }
        );
      })
    );
    return;
  }

  // Pages et assets - Network first, cache fallback
  event.respondWith(
    fetch(request)
      .then((response) => {
        // Cloner et mettre en cache la réponse
        if (response.status === 200) {
          const responseClone = response.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(request, responseClone);
          });
        }
        return response;
      })
      .catch(() => {
        // Fallback au cache
        return caches.match(request).then((cachedResponse) => {
          if (cachedResponse) {
            return cachedResponse;
          }
          // Page principale non trouvée -> page offline
          if (request.mode === 'navigate') {
            return caches.match(OFFLINE_URL);
          }
          return new Response('Ressource non disponible hors ligne', { status: 503 });
        });
      })
  );
});

// Message du client (pour futur refresh manuel du cache)
self.addEventListener('message', (event) => {
  if (event.data === 'skipWaiting') {
    self.skipWaiting();
  }
});
