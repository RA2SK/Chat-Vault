from dataclasses import dataclass


@dataclass(frozen=True)
class ServiceResult:
    data: object
