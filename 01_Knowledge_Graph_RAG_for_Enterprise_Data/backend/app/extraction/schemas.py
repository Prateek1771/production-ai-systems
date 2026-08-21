import re
from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256

from pydantic import BaseModel, ValidationError, field_validator, model_validator


class EntityType(StrEnum):
    PERSON = "Person"
    COMPANY = "Company"
    PRODUCT = "Product"
    TECHNOLOGY = "Technology"
    INDUSTRY = "Industry"
    LOCATION = "Location"


# The Product/Technology boundary needs a statable rule or the model
# splits the same entity across both labels. Product is a named
# commercial offering (Azure, ChatGPT, H100). Technology is a
# capability or architecture (CUDA, transformers, Blackwell).
ENTITY_TYPE_HINTS: dict[EntityType, str] = {
    EntityType.PERSON: "a named individual",
    EntityType.COMPANY: "a named organisation or business",
    EntityType.PRODUCT: "a named commercial offering, such as Azure or ChatGPT",
    EntityType.TECHNOLOGY: "a capability or architecture, such as CUDA or transformers",
    EntityType.INDUSTRY: "a market or sector, such as cloud computing",
    EntityType.LOCATION: "a place, city, or country",
}


class RelationType(StrEnum):
    CEO_OF = "CEO_OF"
    FOUNDED = "FOUNDED"
    WORKS_AT = "WORKS_AT"
    PREVIOUSLY_WORKED_AT = "PREVIOUSLY_WORKED_AT"
    BOARD_MEMBER_OF = "BOARD_MEMBER_OF"
    INVESTED_IN = "INVESTED_IN"
    ACQUIRED = "ACQUIRED"
    PARTNERS_WITH = "PARTNERS_WITH"
    COMPETES_WITH = "COMPETES_WITH"
    SUPPLIES = "SUPPLIES"
    DEVELOPS = "DEVELOPS"
    USES = "USES"
    OPERATES_IN = "OPERATES_IN"
    BASED_ON = "BASED_ON"
    HEADQUARTERED_IN = "HEADQUARTERED_IN"


# Which entity types each relation is allowed to connect. This is the
# check that catches a reversed edge, which no prompt reliably prevents.
RELATION_SIGNATURES: dict[RelationType, tuple[EntityType, EntityType]] = {
    RelationType.CEO_OF: (EntityType.PERSON, EntityType.COMPANY),
    RelationType.FOUNDED: (EntityType.PERSON, EntityType.COMPANY),
    RelationType.WORKS_AT: (EntityType.PERSON, EntityType.COMPANY),
    RelationType.PREVIOUSLY_WORKED_AT: (EntityType.PERSON, EntityType.COMPANY),
    RelationType.BOARD_MEMBER_OF: (EntityType.PERSON, EntityType.COMPANY),
    RelationType.INVESTED_IN: (EntityType.COMPANY, EntityType.COMPANY),
    RelationType.ACQUIRED: (EntityType.COMPANY, EntityType.COMPANY),
    RelationType.PARTNERS_WITH: (EntityType.COMPANY, EntityType.COMPANY),
    RelationType.COMPETES_WITH: (EntityType.COMPANY, EntityType.COMPANY),
    RelationType.SUPPLIES: (EntityType.COMPANY, EntityType.COMPANY),
    RelationType.DEVELOPS: (EntityType.COMPANY, EntityType.PRODUCT),
    RelationType.USES: (EntityType.COMPANY, EntityType.PRODUCT),
    RelationType.OPERATES_IN: (EntityType.COMPANY, EntityType.INDUSTRY),
    RelationType.BASED_ON: (EntityType.PRODUCT, EntityType.TECHNOLOGY),
    RelationType.HEADQUARTERED_IN: (EntityType.COMPANY, EntityType.LOCATION),
}


def normalize_name(name: str) -> str:
    cleaned = re.sub(r"[^\w\s]", " ", name.lower())
    return " ".join(cleaned.split())


def build_entity_id(entity_type: str, name: str) -> str:
    raw = f"{entity_type}:{normalize_name(name)}"
    return sha256(raw.encode("utf-8")).hexdigest()


def _coerce_confidence(value) -> float:
    """Models emit 0.9, "0.9", "high", or nothing. Never fail on this."""

    if value is None:
        return 1.0

    if isinstance(value, str):
        words = {"high": 0.9, "medium": 0.6, "low": 0.3}
        if value.strip().lower() in words:
            return words[value.strip().lower()]
        try:
            value = float(value)
        except ValueError:
            return 1.0

    try:
        number = float(value)
    except (TypeError, ValueError):
        return 1.0

    return min(1.0, max(0.0, number))


class ExtractedEntity(BaseModel):
    name: str
    type: EntityType
    confidence: float = 1.0

    @field_validator("type", mode="before")
    @classmethod
    def _tolerate_casing(cls, value):
        if isinstance(value, str):
            return value.strip().title()
        return value

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_confidence(cls, value):
        return _coerce_confidence(value)

    @field_validator("name")
    @classmethod
    def _require_real_name(cls, value):
        stripped = value.strip()
        if len(stripped) < 2:
            raise ValueError("name too short")
        return stripped


class ExtractedRelation(BaseModel):
    source: str
    type: RelationType
    target: str
    confidence: float = 1.0

    @field_validator("type", mode="before")
    @classmethod
    def _tolerate_casing(cls, value):
        if isinstance(value, str):
            return (
                value.strip()
                .upper()
                .replace(" ", "_")
                .replace("-", "_")
            )
        return value

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_confidence(cls, value):
        return _coerce_confidence(value)

    @model_validator(mode="after")
    def _reject_self_loop(self):
        if normalize_name(self.source) == normalize_name(self.target):
            raise ValueError("source and target are the same entity")
        return self


@dataclass
class Extraction:
    entities: list[ExtractedEntity] = field(default_factory=list)
    relations: list[ExtractedRelation] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)


def validate_extraction(payload: dict) -> Extraction:
    """Keep what is valid, record what is not. Never raise."""

    result = Extraction()

    for raw in payload.get("entities") or []:
        try:
            result.entities.append(ExtractedEntity.model_validate(raw))
        except ValidationError as error:
            result.rejected.append(
                f"entity {raw!r}: {error.errors()[0]['msg']}"
            )

    types_by_name = {
        normalize_name(entity.name): entity.type
        for entity in result.entities
    }

    for raw in payload.get("relations") or []:

        try:
            relation = ExtractedRelation.model_validate(raw)
        except ValidationError as error:
            result.rejected.append(
                f"relation {raw!r}: {error.errors()[0]['msg']}"
            )
            continue

        source_type = types_by_name.get(normalize_name(relation.source))
        target_type = types_by_name.get(normalize_name(relation.target))

        if source_type is None or target_type is None:
            result.rejected.append(
                f"relation {raw!r}: endpoint not in extracted entities"
            )
            continue

        expected_source, expected_target = RELATION_SIGNATURES[relation.type]

        if (source_type, target_type) != (expected_source, expected_target):
            result.rejected.append(
                f"relation {raw!r}: {relation.type} expects "
                f"{expected_source}->{expected_target}, "
                f"got {source_type}->{target_type}"
            )
            continue

        result.relations.append(relation)

    return result


if __name__ == "__main__":

    # Real output from gemma3:1b and gemma3:4b, garbage included.
    payload = {
        "entities": [
            {"name": "NVIDIA Corporation", "type": "Company"},
            {"name": "Jensen Huang", "type": "person"},
            {"name": "Azure", "type": "PRODUCT"},
            {"name": "artificial intelligence", "type": "Concept"},
            {"name": "X", "type": "Company"},
        ],
        "relations": [
            {"source": "Jensen Huang", "type": "ceo of",
             "target": "NVIDIA Corporation"},
            {"source": "NVIDIA Corporation", "type": "CEO_OF",
             "target": "Jensen Huang"},
            {"source": "NVIDIA Corporation", "type": "FOUNDED",
             "target": "NVIDIA Corporation"},
            {"source": "Microsoft", "type": "DEVELOPS",
             "target": "Azure"},
            {"source": "NVIDIA Corporation", "type": "MANAGES",
             "target": "Azure"},
        ],
    }

    result = validate_extraction(payload)

    print("KEPT ENTITIES")
    for entity in result.entities:
        print(
            f"   {entity.name:<24} {entity.type:<10} "
            f"{build_entity_id(entity.type, entity.name)[:12]}"
        )

    print()
    print("KEPT RELATIONS")
    for relation in result.relations:
        print(
            f"   {relation.source:<24} {relation.type:<10} {relation.target}"
        )

    print()
    print("REJECTED")
    for reason in result.rejected:
        print(f"   {reason}")

    assert len(result.entities) == 3, result.entities
    assert len(result.relations) == 1, result.relations
    assert len(result.rejected) == 6, result.rejected

    print()
    print("self-check passed")
