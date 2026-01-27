"""
Queue Manager pour le Scribe temps réel.
Gère le tampon entre les échanges entrants et le traitement Scribe.
"""

import time
from queue import Queue, Empty
from threading import Thread, Event
from typing import Dict, Optional, Callable
from dataclasses import dataclass


@dataclass
class SegmentItem:
    """Un segment en attente de traitement."""
    timestamp: str
    auteur: str
    texte: str
    token_start: int
    received_at: float  # time.time() de réception


class ScribeQueue:
    """
    Tampon entre les échanges entrants et le Scribe.
    
    Usage:
        queue = ScribeQueue(on_processed=callback)
        queue.set_extractor(extractor)
        queue.set_db_insert(insert_fn)
        queue.start()
        
        # Ajouter des segments (non-bloquant)
        queue.put(timestamp, auteur, texte, token_start)
        
        # Arrêter proprement
        queue.stop()
    """
    
    def __init__(self, 
                 on_processed: Optional[Callable[[SegmentItem, Dict], None]] = None,
                 idle_callback: Optional[Callable[[], None]] = None,
                 idle_threshold: float = 5.0):
        """
        Args:
            on_processed: Callback appelé après traitement (segment, metadata)
            idle_callback: Callback appelé quand le Scribe est inactif (pour révision)
            idle_threshold: Secondes d'inactivité avant d'appeler idle_callback
        """
        self._queue: Queue[SegmentItem] = Queue()
        self._stop_event = Event()
        self._worker_thread: Optional[Thread] = None
        self._extractor = None
        self._db_insert_fn = None
        
        self.on_processed = on_processed
        self.idle_callback = idle_callback
        self.idle_threshold = idle_threshold
        
        # Stats
        self.segments_received = 0
        self.segments_processed = 0
        self.last_activity = time.time()
    
    def set_extractor(self, extractor):
        """Injecte l'extracteur (VLLMExtractor, OllamaExtractor, etc.)"""
        self._extractor = extractor
    
    def set_db_insert(self, insert_fn: Callable):
        """Injecte la fonction d'insertion SQL."""
        self._db_insert_fn = insert_fn
    
    def put(self, timestamp: str, auteur: str, texte: str, token_start: int = 0):
        """
        Ajoute un segment à la queue (non-bloquant).
        Appelé par l'agent conversationnel après chaque échange.
        """
        item = SegmentItem(
            timestamp=timestamp,
            auteur=auteur,
            texte=texte,
            token_start=token_start,
            received_at=time.time()
        )
        self._queue.put(item)
        self.segments_received += 1
        self.last_activity = time.time()
        print(f"  📥 Queue: +1 segment (en attente: {self._queue.qsize()})")
    
    def start(self):
        """Démarre le worker thread."""
        if self._worker_thread is not None:
            return
        
        self._stop_event.clear()
        self._worker_thread = Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()
        print("🚀 ScribeQueue démarré")
    
    def stop(self, wait: bool = True):
        """Arrête le worker proprement."""
        self._stop_event.set()
        if wait and self._worker_thread:
            self._worker_thread.join(timeout=10)
        self._worker_thread = None
        print("🛑 ScribeQueue arrêté")
    
    def _worker_loop(self):
        """Boucle principale du worker."""
        while not self._stop_event.is_set():
            try:
                # Attendre un segment (timeout pour vérifier stop_event)
                item = self._queue.get(timeout=1.0)
                self._process_segment(item)
                self._queue.task_done()
                
            except Empty:
                # Queue vide - vérifier si on est idle
                idle_time = time.time() - self.last_activity
                if idle_time > self.idle_threshold and self.idle_callback:
                    self.idle_callback()
                    self.last_activity = time.time()  # Reset pour éviter spam
    
    def _process_segment(self, item: SegmentItem):
        """Traite un segment."""
        if self._extractor is None:
            print("  ⚠️ Pas d'extracteur configuré!")
            return
        
        start = time.time()
        
        # Extraction métadonnées
        metadata = self._extractor.extract(item.texte)
        
        # Insertion SQL
        if self._db_insert_fn:
            self._db_insert_fn(
                timestamp=item.timestamp,
                token_start=item.token_start,
                auteur=item.auteur,
                metadata=metadata
            )
        
        elapsed = time.time() - start
        self.segments_processed += 1
        
        wait_time = start - item.received_at  # Temps d'attente en queue
        print(f"  ✅ Segment traité en {elapsed:.1f}s (attente queue: {wait_time:.1f}s)")
        
        # Callback
        if self.on_processed:
            self.on_processed(item, metadata)
    
    @property
    def pending(self) -> int:
        """Nombre de segments en attente."""
        return self._queue.qsize()
    
    @property
    def is_idle(self) -> bool:
        """True si la queue est vide."""
        return self._queue.empty()
    
    def stats(self) -> Dict:
        """Retourne les statistiques."""
        return {
            "received": self.segments_received,
            "processed": self.segments_processed,
            "pending": self.pending,
            "idle_seconds": round(time.time() - self.last_activity, 1)
        }