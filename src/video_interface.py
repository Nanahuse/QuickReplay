from abc import abstractmethod, ABC

from resolution import Resolution


class VideoInterface(ABC):
    @abstractmethod
    @property
    def resolution(self) -> Resolution:
        pass

    @abstractmethod
    def close(self):
        pass

    @abstractmethod
    def read(self):
        pass

    @abstractmethod
    def stop_record(self):
        pass
