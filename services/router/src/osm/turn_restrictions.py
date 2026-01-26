from typing import Dict, List, Set, Optional, Tuple
from dataclasses import dataclass
from loguru import logger as log


@dataclass
class TurnRestriction:
    relation_id: int
    restriction_type: str
    from_way: int
    via_node: int
    to_way: int
    is_prohibitive: bool
    is_mandatory: bool


class TurnRestrictionManager:
    PROHIBITIVE = {
        'no_left_turn', 'no_right_turn', 'no_straight_on',
        'no_u_turn', 'no_entry', 'no_exit'
    }
    
    MANDATORY = {
        'only_left_turn', 'only_right_turn',
        'only_straight_on', 'only_u_turn'
    }
    
    def __init__(self):
        self.restrictions: List[TurnRestriction] = []
        self._index: Dict[Tuple[int, int], List[TurnRestriction]] = {}
    
    def load_from_osm_relations(self, relations: List[Dict]) -> None:
        count = 0
        for relation in relations:
            if relation.get('tags', {}).get('type') != 'restriction':
                continue
            
            restriction = self._parse_restriction(relation)
            if restriction:
                self.restrictions.append(restriction)
                key = (restriction.from_way, restriction.via_node)
                if key not in self._index:
                    self._index[key] = []
                self._index[key].append(restriction)
                count += 1
        
        log.info(f"Loaded {count} turn restrictions.")
    
    def _parse_restriction(self, relation: Dict) -> Optional[TurnRestriction]:
        tags = relation.get('tags', {})
        members = relation.get('members', [])
        
        restriction_type = tags.get('restriction')
        if not restriction_type:
            return None
        
        from_way = None
        via_node = None
        to_way = None
        
        for member in members:
            role = member.get('role')
            ref = member.get('ref')
            member_type = member.get('type')
            
            if role == 'from' and member_type == 'way':
                from_way = ref
            elif role == 'via' and member_type == 'node':
                via_node = ref
            elif role == 'to' and member_type == 'way':
                to_way = ref
        
        if from_way is None or via_node is None or to_way is None:
            return None
        
        is_prohibitive = restriction_type in self.PROHIBITIVE
        is_mandatory = restriction_type in self.MANDATORY
        
        return TurnRestriction(
            relation_id=relation['id'],
            restriction_type=restriction_type,
            from_way=from_way,
            via_node=via_node,
            to_way=to_way,
            is_prohibitive=is_prohibitive,
            is_mandatory=is_mandatory
        )
