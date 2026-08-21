from dataclasses import dataclass, field


@dataclass
class Entity:
    entity_id: str
    name: str
    entity_type: str
    aliases: list[str] = field(default_factory=list)


@dataclass
class Relation:
    source_id: str
    target_id: str
    relation_type: str
    chunk_id: str
