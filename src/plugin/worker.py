"""Cruzamentos em uma thread própria; objetos QGIS nunca atravessam threads."""

import copy
import json
from collections import OrderedDict
from queue import Queue
from threading import Event

from qgis.core import QgsCoordinateTransformContext, QgsProject
from qgis.PyQt.QtCore import QEventLoop, QThread, pyqtSignal

from qgis_plugin_microcredito.application.hashing import file_sha256

from .analysis import EnvironmentalAnalyzer, source_signature


class EnvironmentalWorker(QThread):
    completed = pyqtSignal(object)

    def __init__(self, sources):
        super().__init__()
        self.sources = list(sources)
        self.context = QgsCoordinateTransformContext(
            QgsProject.instance().transformContext()
        )
        self.jobs = Queue()
        self.busy = False
        self.cancel_event = Event()
        self.start()

    def run(self):
        analyzer = EnvironmentalAnalyzer(self.sources, context=self.context)
        cache = OrderedDict()
        try:
            while True:
                path = self.jobs.get()
                if path is None:
                    break
                try:
                    signatures = [source_signature(source) for source in self.sources]
                    key = (file_sha256(path), tuple(signatures))
                    if key in cache:
                        result = copy.deepcopy(cache[key])
                        cache.move_to_end(key)
                    else:
                        # Converter atributos QVariant/QDate para valores transportáveis.
                        result = json.loads(
                            json.dumps(
                                analyzer.analyze(
                                    path, cancel_check=self.cancel_event.is_set
                                ),
                                ensure_ascii=False,
                                default=str,
                            )
                        )
                        cache[key] = copy.deepcopy(result)
                        if len(cache) > 32:
                            cache.popitem(last=False)
                    self.completed.emit((result, None))
                except Exception as exc:
                    self.completed.emit((None, str(exc)))
        finally:
            analyzer._layers.clear()

    def analyze(self, path):
        if self.busy:
            raise RuntimeError("Já existe um cruzamento em andamento.")
        self.busy = True
        loop = QEventLoop()
        response = []

        def receive(value):
            response.append(value)
            loop.quit()

        self.completed.connect(receive)
        try:
            self.cancel_event.clear()
            self.jobs.put(str(path))
            loop.exec_()
            result, error = response[0]
            if error:
                raise RuntimeError(error)
            return result
        finally:
            self.completed.disconnect(receive)
            self.busy = False

    def cancel_current(self):
        self.cancel_event.set()

    def close(self):
        self.cancel_current()
        self.jobs.put(None)
        self.wait()


def run_environment(path, sources):
    worker = EnvironmentalWorker(sources)
    try:
        return worker.analyze(path)
    finally:
        worker.close()
