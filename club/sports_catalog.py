"""
Sports Catalog - Centralized Shared Data for 10 Sports
Champions Club Multi-Sport Facility
"""

from typing import Dict, Any, List

SPORTS_CATALOG: Dict[str, Dict[str, Any]] = {
    'tennis': {
        'slug': 'tennis',
        'name': 'Tennis',
        'icon': '🎾',
        'category': 'Racquet Sport',
        'surface_types': 'Championship French Clay & Tournament Hardcourt',
        'players_per_session': '2 – 4 Players',
        'description': (
            'Experience master circuit tennis on championship French Red Clay and tournament hardcourt surfaces. '
            'Features tournament standard lighting, shaded player benches, and automated ball machines.'
        ),
        'equipment_available': 'Head & Wilson Pro Racquets, Tour Balls, Vibration Dampeners in Pro Shop',
        'booking_notice': 'Standard 60-minute match play with court lighting included.',
    },
    'badminton': {
        'slug': 'badminton',
        'name': 'Badminton',
        'icon': '🏸',
        'category': 'Indoor Racquet',
        'surface_types': 'BWF-Approved Shock-Absorbing Synthetic Mat on Hardwood',
        'players_per_session': '2 – 4 Players',
        'description': (
            'High-velocity indoor singles and doubles badminton on BWF-standard shock absorption flooring '
            'with shadowless LED overhead illumination and climate control.'
        ),
        'equipment_available': 'Yonex Carbon Racquets & Feather Shuttlecocks available at Reception',
        'booking_notice': 'Non-marking indoor court shoes required.',
    },
    'squash': {
        'slug': 'squash',
        'name': 'Squash',
        'icon': '🟡',
        'category': 'Indoor Wall Racquet',
        'surface_types': 'WSF Hard Maple Flooring & Clear Glass Back Wall',
        'players_per_session': '2 Players',
        'description': (
            'Intense indoor court squash featuring tournament glass-back spectator galleries, '
            'true-bounce calibrated front wall, and regulated air conditioning.'
        ),
        'equipment_available': 'Dunlop Pro Squash Balls & Protective Eyewear in Pro Shop',
        'booking_notice': 'Goggles mandatory for juniors; non-marking shoes required.',
    },
    'cricket': {
        'slug': 'cricket',
        'name': 'Cricket',
        'icon': '🏏',
        'category': 'Bat & Ball Turf',
        'surface_types': 'All-Weather AstroTurf Practice Pitch with Enclosed Netting',
        'players_per_session': '2 – 10 Players',
        'description': (
            'Dedicated outdoor and semi-enclosed batting and bowling practice nets featuring '
            'variable-speed bowling machine options and full boundary netting.'
        ),
        'equipment_available': 'English Willow Bats, Leather/Tennis Balls, Helmets & Protective Pads',
        'booking_notice': 'Protective gear required when facing leather balls.',
    },
    'football': {
        'slug': 'football',
        'name': 'Football',
        'icon': '⚽',
        'category': 'Turf Field Sport',
        'surface_types': 'FIFA-Quality Artificial Turf',
        'players_per_session': '10 – 14 Players (5v5 / 7v7)',
        'description': (
            'Rapid-pace 5-a-side and 7-a-side football on all-weather synthetic turf with '
            'perimeter shock netting and stadium floodlights.'
        ),
        'equipment_available': 'Match Footballs & Training Bibs at Clubhouse reception',
        'booking_notice': 'Turf boots or trainers recommended; metal studs prohibited.',
    },
    'basketball': {
        'slug': 'basketball',
        'name': 'Basketball',
        'icon': '🏀',
        'category': 'Hardcourt Sport',
        'surface_types': 'Maple Hardwood / Polyurethane Outdoor Court',
        'players_per_session': '6 – 10 Players (3v3 / Full Court)',
        'description': (
            'Full-court and half-court basketball with spring-action breakaway rims, '
            'perimeter rebound padding, and digital shot clocks.'
        ),
        'equipment_available': 'Spalding Official Game Balls available at Counter',
        'booking_notice': 'Indoor court shoes required for hardwood arena.',
    },
    'volleyball': {
        'slug': 'volleyball',
        'name': 'Volleyball',
        'icon': '🏐',
        'category': 'Court & Sand',
        'surface_types': 'Indoor Hardwood / Sand Beach Arena',
        'players_per_session': '8 – 12 Players',
        'description': (
            'Standard competition height adjustable net volleyball courts for power league matches, '
            'club tournaments, and social pick-up games.'
        ),
        'equipment_available': 'Mikasa Official Volleyballs & Antennas provided',
        'booking_notice': 'Net height adjusted upon arrival for Men, Women, or Mixed play.',
    },
    'table_tennis': {
        'slug': 'table_tennis',
        'name': 'Table Tennis',
        'icon': '🏓',
        'category': 'Indoor Table Sport',
        'surface_types': 'ITTF Approved 25mm Top Indoor Arena',
        'players_per_session': '2 – 4 Players',
        'description': (
            'High-precision table tennis lounge with anti-glare competition tables, '
            'barrier partitions, and speed-spin flooring.'
        ),
        'equipment_available': 'Stiga Carbon Bats & 3-Star Balls available at Club Shop',
        'booking_notice': 'Singles and doubles ladder competitions held weekly.',
    },
    'pickleball': {
        'slug': 'pickleball',
        'name': 'Pickleball',
        'icon': '🥍',
        'category': 'Racquet & Paddle',
        'surface_types': 'Cushioned Acrylic Outdoor Court',
        'players_per_session': '2 – 4 Players',
        'description': (
            'Fast-growing paddle sport blending tennis, badminton, and ping-pong. '
            'Low-impact, high-tactical rallies in a welcoming club setting.'
        ),
        'equipment_available': 'Composite Paddles & Outdoor Perforated Balls in Pro Shop',
        'booking_notice': 'Paddle demo sessions available on weekends.',
    },
    'swimming': {
        'slug': 'swimming',
        'name': 'Swimming',
        'icon': '🏊',
        'category': 'Aquatics',
        'surface_types': '25-Meter Heated Lap Pool (6 Lanes)',
        'players_per_session': '1 – 6 Swimmers per Lane',
        'description': (
            'Heated 25-meter half-Olympic lap swimming facility with ozone purification, '
            'dedicated lane dividers, and poolside certified lifeguards.'
        ),
        'equipment_available': 'Kickboards, Pull Buoys & Goggles available at Pool Pavilion',
        'booking_notice': 'Swim caps mandatory; shower required before pool entry.',
    },
}


def get_sport_data(slug: str) -> Dict[str, Any] | None:
    """Returns static data for a sport slug, or None if invalid."""
    return SPORTS_CATALOG.get(slug.lower())


def get_all_sports_with_facilities(court_queryset=None) -> List[Dict[str, Any]]:
    """
    Returns list of all 10 sports annotated with real database facilities.
    """
    from club.models import Court

    if court_queryset is None:
        court_queryset = Court.objects.filter(active=True)

    sports_list = []
    for slug, info in SPORTS_CATALOG.items():
        courts = [c for c in court_queryset if c.sport == slug]
        sports_list.append({
            **info,
            'courts': courts,
            'facility_count': len(courts),
            'has_facilities': len(courts) > 0,
        })
    return sports_list
