"""Turn Restrictions - Load and check OSM turn restrictions

Processes OSM relations with type=restriction to enforce turn rules in routing.
"""
from typing import Dict, List, Set, Optional, Tuple
from dataclasses import dataclass
import structlog

log = structlog.get_logger(__name__)


@dataclass
class TurnRestriction:
    """A single turn restriction from OSM"""
    relation_id: int
    restriction_type: str  # e.g., "no_left_turn", "only_straight_on"
    from_way: int  # OSM way ID
    via_node: int  # OSM node ID (or via_way for complex)
    to_way: int  # OSM way ID
    
    # Parsed flags
    is_prohibitive: bool  # True for "no_*" restrictions
    is_mandatory: bool  # True for "only_*" restrictions


class TurnRestrictionManager:
    """Manager for turn restrictions"""
    
    # Restriction types
    PROHIBITIVE = {
        'no_left_turn',
        'no_right_turn',
        'no_straight_on',
        'no_u_turn',
        'no_entry',
        'no_exit'
    }
    
    MANDATORY = {
        'only_left_turn',
        'only_right_turn',
        'only_straight_on',
        'only_u_turn'
    }
    
    def __init__(self):
        """Initialize manager"""
        self.restrictions: List[TurnRestriction] = []
        # Index: (from_way, via_node) -> [restrictions]
        self._index: Dict[Tuple[int, int], List[TurnRestriction]] = {}
        log.info("turn_restriction_manager_initialized")
    
    def load_from_osm_relations(self, relations: List[Dict]) -> None:
        """Load restrictions from OSM relations
        
        Args:
            relations: List of OSM relation dicts
        """
        count = 0
        for relation in relations:
            if relation.get('tags', {}).get('type') != 'restriction':
                continue
            
            restriction = self._parse_restriction(relation)
            if restriction:
                self.restrictions.append(restriction)
                
                # Index by (from_way, via_node)
                key = (restriction.from_way, restriction.via_node)
                if key not in self._index:
                    self._index[key] = []
                self._index[key].append(restriction)
                count += 1
        
        log.info(
            "turn_restrictions_loaded",
            count=count,
            indexed_keys=len(self._index)
        )
    
    def _parse_restriction(self, relation: Dict) -> Optional[TurnRestriction]:
        """Parse single OSM restriction relation"""
        tags = relation.get('tags', {})
        members = relation.get('members', [])
        
        restriction_type = tags.get('restriction')
        if not restriction_type:
            return None
        
        # Extract members
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
    
    def is_turn_allowed(
        self,
        from_way_id: int,
        via_node_id: int,
        to_way_id: int
    ) -> bool:
        """Check if turn is allowed
        
        Args:
            from_way_id: Source OSM way
            via_node_id: Intersection node
            to_way_id: Target OSM way
            
        Returns:
            True if turn is allowed, False otherwise
        """
        key = (from_way_id, via_node_id)
        restrictions = self._index.get(key, [])
        
        if not restrictions:
            return True  # No restrictions = allowed
        
        # Check prohibitive restrictions
        for r in restrictions:
            if r.is_prohibitive and r.to_way == to_way_id:
                return False  # Explicitly forbidden
        
        # Check mandatory restrictions
        mandatory = [r for r in restrictions if r.is_mandatory]
        if mandatory:
            # If any mandatory restriction exists, only those to_ways allowed
            allowed_ways = {r.to_way for r in mandatory}
            return to_way_id in allowed_ways
        
        return True  # No prohibitive match, no mandatory = allowed
    
    def get_restrictions_at_node(self, via_node_id: int) -> List[TurnRestriction]:
        """Get all restrictions passing through a node
        
        Args:
            via_node_id: Node ID
            
        Returns:
            List of restrictions
        """
        result = []
        for restrictions in self._index.values():
            for r in restrictions:
                if r.via_node == via_node_id:
                    result.append(r)
        return result
    
    def get_allowed_ways_from(
        self,
        from_way_id: int,
        via_node_id: int,
        candidate_ways: Set[int]
    ) -> Set[int]:
        """Get allowed outgoing ways from intersection
        
        Args:
            from_way_id: Incoming way
            via_node_id: Intersection node
            candidate_ways: All possible outgoing ways
            
        Returns:
            Set of allowed way IDs
        """
        key = (from_way_id, via_node_id)
        restrictions = self._index.get(key, [])
        
        if not restrictions:
            return candidate_ways  # No restrictions
        
        # Check mandatory restrictions first
        mandatory = [r for r in restrictions if r.is_mandatory]
        if mandatory:
            allowed = {r.to_way for r in mandatory}
            return allowed & candidate_ways
        
        # Filter out prohibitive restrictions
        prohibited = {r.to_way for r in restrictions if r.is_prohibitive}
        return candidate_ways - prohibited
