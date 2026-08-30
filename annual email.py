from pathlib import Path
import webbrowser

import pandas as pd
import streamlit as st
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import URL, create_engine, text


# settings

Person_id = 16202
Report_year = 2023
Dashboard_url = "https://example.org/mammalweb-dashboard"

Months = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

Year_start = "2023-01-01"
Data_end = "2024-01-01"


# database queries

@st.cache_resource
def get_engine():
    connection_url = URL.create(
        drivername="mysql+pymysql",
        username=st.secrets["mysql"]["user"],
        password=st.secrets["mysql"]["password"],
        host=st.secrets["mysql"]["host"],
        port=int(st.secrets["mysql"]["port"]),
        database=st.secrets["mysql"]["database"],
    )

    return create_engine(
        connection_url,
        pool_pre_ping=True,
    )


@st.cache_data(ttl=300)
def query_database(sql, params=None):
    engine = get_engine()
    with engine.connect() as connection:
        return pd.read_sql(text(sql), connection, params=params or {})


def annual_params(person_id):
    return {
        "person_id": person_id,
        "start_date": Year_start,
        "end_date": Data_end
    }


def get_role(person_id):
    sql = """
    SELECT
        EXISTS(
            SELECT 1
            FROM Animal
            WHERE person_id = :person_id
              AND `timestamp` >= :start_date
              AND `timestamp` < :end_date
        ) AS is_spotter,

        EXISTS(
            SELECT 1
            FROM Photo
            WHERE person_id = :person_id
              AND uploaded >= :start_date
              AND uploaded < :end_date
        ) AS is_trapper;
    """

    row = query_database(sql, annual_params(person_id)).iloc[0]
    return bool(row["is_spotter"]), bool(row["is_trapper"])


def get_photos_classified(person_id):
    sql = """
    SELECT
        COUNT(DISTINCT photo_id) AS classified_photos
    FROM Animal
    WHERE person_id = :person_id
      AND `timestamp` >= :start_date
      AND `timestamp` < :end_date;
    """

    result = query_database(sql, annual_params(person_id))
    return int(result.iloc[0]["classified_photos"])


def get_monthly_spotter(person_id):
    sql = """
    SELECT
        MONTH(`timestamp`) AS month,
        COUNT(DISTINCT photo_id) AS contribution_count
    FROM Animal
    WHERE person_id = :person_id
      AND `timestamp` >= :start_date
      AND `timestamp` < :end_date
    GROUP BY MONTH(`timestamp`)
    ORDER BY month;
    """

    result = query_database(sql, annual_params(person_id))
    month_counts = {}
    for _, row in result.iterrows():
        month_counts[int(row["month"])] = int(row["contribution_count"])

    values = []
    for month in range(1, 13):
        values.append(month_counts.get(month, 0))
    return values


def format_story_date(value):
    if value is None or pd.isna(value):
        return None

    date_value = pd.to_datetime(value)
    return f"{date_value.day} {Months[date_value.month - 1]}"


def get_longest_streak(person_id):
    sql = """
    WITH active_dates AS (
        SELECT DISTINCT
            DATE(`timestamp`) AS activity_date
        FROM Animal
        WHERE person_id = :person_id
          AND `timestamp` >= :start_date
          AND `timestamp` < :end_date
    ),

    numbered_dates AS (
        SELECT
            activity_date,
            ROW_NUMBER() OVER (
                ORDER BY activity_date
            ) AS row_num
        FROM active_dates
    ),

    grouped_dates AS (
        SELECT
            activity_date,
            DATE_SUB(
                activity_date,
                INTERVAL row_num DAY
            ) AS streak_group
        FROM numbered_dates
    ),

    streaks AS (
        SELECT
            MIN(activity_date) AS start_date,
            MAX(activity_date) AS end_date,
            COUNT(*) AS streak_length
        FROM grouped_dates
        GROUP BY streak_group
    )

    SELECT
        start_date,
        end_date,
        streak_length
    FROM streaks
    ORDER BY streak_length DESC, end_date DESC
    LIMIT 1;
    """

    result = query_database(sql, annual_params(person_id))

    if result.empty:
        return None, None, 0

    row = result.iloc[0]
    return (
        format_story_date(row["start_date"]),
        format_story_date(row["end_date"]),
        int(row["streak_length"]),
    )


def get_spotter_ranking(person_id):
    sql = """
    WITH user_counts AS (
        SELECT
            person_id,
            COUNT(DISTINCT photo_id) AS classification_count
        FROM Animal
        WHERE `timestamp` >= :start_date
          AND `timestamp` < :end_date
        GROUP BY person_id
    ),

    ranked_users AS (
        SELECT
            person_id,
            classification_count,
            RANK() OVER (
                ORDER BY classification_count DESC
            ) AS user_rank,
            COUNT(*) OVER () AS total_users
        FROM user_counts
    )

    SELECT
        user_rank,
        total_users
    FROM ranked_users
    WHERE person_id = :person_id;
    """

    result = query_database(sql, annual_params(person_id))

    if result.empty:
        return 0, 0, None

    row = result.iloc[0]
    user_rank = int(row["user_rank"])
    total_users = int(row["total_users"])
    top_percent = user_rank / total_users * 100 if total_users else None

    return user_rank, total_users, top_percent


def get_top_species_spotter(person_id):
    sql = """
    SELECT
        o.option_name AS species_name,
        COUNT(DISTINCT a.photo_id) AS classified_photos
    FROM Animal AS a
    JOIN Options AS o
        ON a.species = o.option_id
    WHERE a.person_id = :person_id
      AND a.`timestamp` >= :start_date
      AND a.`timestamp` < :end_date
      AND o.struc = 'mammal'
    GROUP BY
        o.option_id,
        o.option_name
    ORDER BY classified_photos DESC
    LIMIT 3;
    """

    result = query_database(sql, annual_params(person_id))

    species = []
    for _, row in result.iterrows():
        species.append((str(row["species_name"]), int(row["classified_photos"])))
    return species

#Expert_conflicting' meaning exclude MammalWeb's internal expert review project
def get_spotter_project_contributions(person_id):
    sql = """
    SELECT
        pr.project_name,
        COUNT(DISTINCT a.photo_id) AS contribution_count
    FROM Animal AS a

    JOIN Photo AS p
        ON a.photo_id = p.photo_id

    JOIN (
        SELECT DISTINCT
            site_id,
            project_id
        FROM ProjectSiteMap
    ) AS psm
        ON p.site_id = psm.site_id

    JOIN Project AS pr
        ON psm.project_id = pr.project_id

    WHERE a.person_id = :person_id
      AND a.`timestamp` >= :start_date
      AND a.`timestamp` < :end_date
      AND pr.project_name IS NOT NULL
      AND pr.project_name <> ''
      AND pr.project_name <> 'Expert_conflicting'

    GROUP BY
        pr.project_id,
        pr.project_name

    ORDER BY contribution_count DESC;
    """

    result = query_database(sql, annual_params(person_id))

    return result.to_dict("records")


def get_trapper_project_contributions(person_id):
    sql = """
    SELECT
        pr.project_name,
        COUNT(DISTINCT p.sequence_id) AS contribution_count
    FROM Photo AS p

    JOIN (
        SELECT DISTINCT
            site_id,
            project_id
        FROM ProjectSiteMap
    ) AS psm
        ON p.site_id = psm.site_id

    JOIN Project AS pr
        ON psm.project_id = pr.project_id

    WHERE p.person_id = :person_id
      AND p.uploaded >= :start_date
      AND p.uploaded < :end_date
      AND pr.project_name IS NOT NULL
      AND pr.project_name <> ''
      AND pr.project_name <> 'Expert_conflicting'

    GROUP BY
        pr.project_id,
        pr.project_name

    ORDER BY contribution_count DESC;
    """

    result = query_database(sql, annual_params(person_id))

    return result.to_dict("records")


def get_sequences_uploaded(person_id):
    sql = """
    SELECT
        COUNT(DISTINCT sequence_id) AS uploaded_sequences
    FROM Photo
    WHERE person_id = :person_id
      AND uploaded >= :start_date
      AND uploaded < :end_date;
    """

    result = query_database(sql, annual_params(person_id))
    return int(result.iloc[0]["uploaded_sequences"])


def get_trapper_sites(person_id):
    sql = """
    SELECT
        COUNT(DISTINCT site_id) AS site_count
    FROM Photo
    WHERE person_id = :person_id
      AND uploaded >= :start_date
      AND uploaded < :end_date;
    """

    result = query_database(sql, annual_params(person_id))
    return int(result.iloc[0]["site_count"])


def get_monthly_trapper(person_id):
    sql = """
    SELECT
        MONTH(uploaded) AS month,
        COUNT(DISTINCT sequence_id) AS contribution_count
    FROM Photo
    WHERE person_id = :person_id
      AND uploaded >= :start_date
      AND uploaded < :end_date
    GROUP BY MONTH(uploaded)
    ORDER BY month;
    """

    result = query_database(sql, annual_params(person_id))
    month_counts = {}
    for _, row in result.iterrows():
        month_counts[int(row["month"])] = int(row["contribution_count"])

    values = []
    for month in range(1, 13):
        values.append(month_counts.get(month, 0))
    return values


def get_trapper_top_identified_species(person_id):
    sql = """
    WITH species_votes AS (
        SELECT
            p.sequence_id,
            a.species,
            COUNT(*) AS vote_count
        FROM Photo AS p

        JOIN Animal AS a
            ON p.photo_id = a.photo_id

        JOIN Options AS o
            ON a.species = o.option_id

        WHERE p.person_id = :person_id
          AND p.uploaded >= :start_date
          AND p.uploaded < :end_date
          AND p.sequence_id IS NOT NULL
          AND a.species IS NOT NULL
          AND o.struc = 'mammal'

        GROUP BY
            p.sequence_id,
            a.species
    ),

    ranked_species AS (
        SELECT
            sequence_id,
            species,
            vote_count,
            ROW_NUMBER() OVER (
                PARTITION BY sequence_id
                ORDER BY vote_count DESC, species
            ) AS species_rank
        FROM species_votes
    ),

    species_totals AS (
        SELECT
            species,
            COUNT(*) AS sequence_count
        FROM ranked_species
        WHERE species_rank=1
        GROUP BY species
    )

    SELECT
        o.option_name AS species_name,
        st.sequence_count
    FROM species_totals AS st

    JOIN Options AS o
        ON st.species = o.option_id

    ORDER BY
        st.sequence_count DESC,
        o.option_name

    LIMIT 1;
    """

    result = query_database(sql, annual_params(person_id))

    if result.empty:
        return None, 0

    row = result.iloc[0]
    return (
        str(row["species_name"]),
        int(row["sequence_count"]),
    )


def get_trapper_effort_days(person_id):
    sql = """
    SELECT
        COALESCE(
            SUM(deployment_days),
            0
        ) AS camera_days
    FROM (
        SELECT DISTINCT
            u.upload_id,
            GREATEST(
                DATEDIFF(u.collection_date, u.deployment_date),
                0
            ) AS deployment_days
        FROM Photo AS p
        JOIN `Upload` AS u
            ON p.upload_id = u.upload_id
        WHERE p.person_id = :person_id
          AND p.uploaded >= :start_date
          AND p.uploaded < :end_date
          AND u.deployment_date IS NOT NULL
          AND u.collection_date IS NOT NULL
    ) AS deployments;
    """

    result = query_database(sql, annual_params(person_id))
    return int(result.iloc[0]["camera_days"])


def build_email_data(person_id):
    is_spotter, is_trapper = get_role(person_id)

    spotter_project_contributions = []
    trapper_project_contributions = []

    if is_spotter:
        spotter_project_contributions = get_spotter_project_contributions(person_id)

    if is_trapper:
        trapper_project_contributions = get_trapper_project_contributions(person_id)

    data = {
        "person_id": person_id,
        "name": "MammalWeb user",
        "year": Report_year,
        "period_start": f"1 January {Report_year}",
        "period_end": f"31 December {Report_year}",
        "dashboard_url": Dashboard_url,
        "is_spotter": is_spotter,
        "is_trapper": is_trapper,
        "spotter_project_contributions": spotter_project_contributions,
        "trapper_project_contributions": trapper_project_contributions,
    }

    if is_spotter:
        streak_start, streak_end, streak_length = get_longest_streak(person_id)
        rank, total_spotters, top_percent = get_spotter_ranking(person_id)

        data["spotter"] = {
            "photos_classified": get_photos_classified(person_id),
            "longest_streak": streak_length,
            "streak_start": streak_start,
            "streak_end": streak_end,
            "top_percent": top_percent,
            "rank": rank,
            "total_spotters": total_spotters,
            "monthly_activity": get_monthly_spotter(person_id),
            "top_species": get_top_species_spotter(person_id),
        }

    if is_trapper:
        top_species_name, top_species_sequences = get_trapper_top_identified_species(person_id)

        data["trapper"] = {
            "sequences_uploaded": get_sequences_uploaded(person_id),
            "sites": get_trapper_sites(person_id),
            "camera_days": get_trapper_effort_days(person_id),
            "monthly_activity": get_monthly_trapper(person_id),
            "top_identified_species": top_species_name,
            "top_species_sequences": top_species_sequences,
        }

    return data


# story functions

def story(
    story_id,
    category,
    score,
    eyebrow,
    title,
    text,
    number=None,
    number_label=None,
    theme="cream",
    role="general",
    reflection=None,
    project_bars=None,
    project_sections=None,
    participation_sections=None,
):
    return {
        "story_id": story_id,
        "category": category,
        "score": score,
        "eyebrow": eyebrow,
        "title": title,
        "text": text,
        "number": number,
        "number_label": number_label,
        "theme": theme,
        "role": role,
        "reflection": reflection,
        "project_bars": project_bars or [],
        "project_sections": project_sections or [],
        "participation_sections": participation_sections or [],
    }


# opening and ending text

def build_opening(data):
    is_spotter = bool(data.get("is_spotter"))
    is_trapper = bool(data.get("is_trapper"))

    if is_spotter and is_trapper:
        return {
            "headline": "You saw MammalWeb from both sides this year.",
            "text": (
                "You created wildlife observations as a Trapper and helped "
                "interpret camera-trap footage as a Spotter."
            ),
        }

    if is_spotter:
        return {
            "headline": "This was a year of careful observation.",
            "text": "You helped turn wildlife images into identifiable records.",
        }

    return {
        "headline": "This was a year spent watching the landscape.",
        "text": "Your cameras created a record of wildlife moving through MammalWeb sites.",
    }


def build_impact(data):
    is_spotter = bool(data.get("is_spotter"))
    is_trapper = bool(data.get("is_trapper"))

    if is_spotter and is_trapper:
        return {
            "headline": "You connected both ends of the process.",
            "text": (
                "Your deployments created wildlife observations, while your "
                "classifications helped turn them into structured records."
            ),
        }

    if is_spotter:
        return {
            "headline": "You helped make wildlife footage understandable.",
            "text": "Each classification made the collection easier to search and analyse.",
        }

    return {
        "headline": "You extended MammalWeb's view of the landscape.",
        "text": "Your deployments added observations that might otherwise have gone unseen.",
    }


# build stories

def analyse_participation_pattern(monthly, role_label, unit_label):
    values = [int(value) for value in monthly[:12]]
    values += [0] * (12 - len(values))

    total = sum(values)
    if total <= 0:
        return None

    active_months = 0
    for value in values:
        if value > 0:
            active_months += 1

    busiest_value = max(values)
    busiest_index = values.index(busiest_value)
    busiest_month = Months[busiest_index]
    busiest_share = busiest_value / total
    top_three_share = sum(sorted(values, reverse=True)[:3]) / total

    if active_months >= 9 and busiest_share < 0.20:
        pattern_label = "Steady"
        headline = "You kept returning throughout the year."
        text_value = (
            f"Your {unit_label} were spread across {active_months} months. "
            f"{busiest_month} was busiest, but only one part of a sustained year."
        )
        number = str(active_months)
        number_label = "active months"
        reflection = (
            "This suggests that your contribution was sustained across much "
            "of the year rather than concentrated in a short period."
        )

    elif busiest_share >= 0.35 or top_three_share >= 0.70:
        pattern_label = "Concentrated"
        headline = f"{busiest_month} defined this side of your year."
        text_value = (
            f"Your {unit_label} were concentrated, with {busiest_month} "
            "marking the peak."
        )
        number = f"{busiest_share:.0%}"
        number_label = f"of your {unit_label} in your busiest month"
        reflection = (
            "This shows that much of your activity took place within a smaller "
            "part of the year, creating a clear seasonal peak."
        )

    else:
        pattern_label = "Regular bursts"
        headline = "You contributed in regular bursts."
        text_value = (
            f"You returned across {active_months} months, with "
            f"{busiest_month} as the strongest point."
        )
        number = str(active_months)
        number_label = "active months"
        reflection = (
            "Your activity was spread across several parts of the year, with "
            "periods of stronger contribution between quieter months."
        )

    return {
        "role_label": role_label,
        "unit_label": unit_label,
        "pattern_label": pattern_label,
        "headline": headline,
        "text": text_value,
        "reflection": reflection,
        "number": number,
        "number_label": number_label,
        "busiest_month": busiest_month,
        "busiest_share": busiest_share,
    }


def participation_story(data):
    is_spotter = bool(data.get("is_spotter"))
    is_trapper = bool(data.get("is_trapper"))
    sections = []

    if is_spotter:
        spotter_section = analyse_participation_pattern(
            data.get("spotter", {}).get("monthly_activity", []),
            "Spotter",
            "classified photos",
        )
        if spotter_section is None:
            raise ValueError(
                "The user is marked as a Spotter, but no Spotter monthly "
                "activity was found for the mandatory participation story."
            )
        sections.append(spotter_section)

    if is_trapper:
        trapper_section = analyse_participation_pattern(
            data.get("trapper", {}).get("monthly_activity", []),
            "Trapper",
            "uploaded sequences",
        )
        if trapper_section is None:
            raise ValueError(
                "The user is marked as a Trapper, but no Trapper monthly "
                "activity was found for the mandatory participation story."
            )
        sections.append(trapper_section)

    if is_spotter and is_trapper:
        return story(
            "participation_pattern",
            "participation",
            100,
            "Your participation pattern · Spotter + Trapper",
            "Two roles, two rhythms of participation.",
            (
                "Your classifications and uploads are shown separately because "
                "they represent different kinds of activity."
            ),
            theme="amber",
            role="both",
            participation_sections=sections,
        )

    section = sections[0]
    role_name = section["role_label"]

    return story(
        "participation_pattern",
        "participation",
        100,
        f"Your {role_name} participation pattern · {section['pattern_label']}",
        section["headline"],
        section["text"],
        section["number"],
        section["number_label"],
        "amber" if section["pattern_label"] == "Concentrated" else "sage",
        role=role_name.lower(),
        reflection=section["reflection"],
    )


def analyse_project_focus(rows, role_label, unit_label):
    projects = []
    for item in rows:
        if item.get("project_name") and int(item.get("contribution_count", 0)) > 0:
            projects.append({
                "project_name": str(item["project_name"]),
                "contribution_count": int(item["contribution_count"]),
            })

    if not projects:
        return {
            "role_label": role_label,
            "unit_label": unit_label,
            "focus_label": "Project data unavailable",
            "headline": "Your activity could not be linked to a named project.",
            "text": (
                f"Your {unit_label} are included in your {Report_year} record, but the "
                "current database does not connect them to a named MammalWeb project."
            ),
            "top_project_name": "No linked project",
            "top_percentage": 0.0,
            "project_bars": [],
            "has_project_data": False,
        }

    projects.sort(
        key=lambda item: item["contribution_count"],
        reverse=True,
    )

    total = sum(item["contribution_count"] for item in projects)

    for item in projects:
        percentage = item["contribution_count"] / total * 100
        item["percentage"] = round(percentage, 1)
        item["bar_width"] = round(percentage)
        item["remainder_width"] = 100 - item["bar_width"]

    top = projects[0]
    top_share = top["percentage"] / total
    project_count = len(projects)

    if project_count == 1 or top_share >= 0.80:
        focus_label = "Single focus"
        headline = "One project clearly defined this side of your year."
        text_value = (
            f"{top['percentage']:.1f}% of your {unit_label} supported "
            f"{top['project_name']}."
        )
        reflection = (
            "Your contribution was strongly centred on one project, giving "
            "this part of your year a clear project focus."
        )
    elif project_count >= 5 and top_share < 0.40:
        focus_label = "Wide-ranging"
        headline = "You explored across MammalWeb projects."
        text_value = (
            f"You supported {project_count} projects, with no single project "
            f"dominating your {unit_label}."
        )
        reflection = (
            "Your contribution was distributed across a broad range of projects, "
            "showing a more varied pattern of participation."
        )
    else:
        focus_label = "Focused mix"
        headline = "You had a clear favourite, but still explored."
        text_value = (
            f"{top['percentage']:.1f}% of your {unit_label} supported "
            f"{top['project_name']}; the rest was shared across "
            f"{project_count - 1} other project"
            f"{'' if project_count == 2 else 's'}."
        )
        reflection = (
            "Your activity combined a clear main project with contributions "
            "to other parts of MammalWeb."
        )

    bars = projects[:3]

    if len(projects) > 3:
        other_count = sum(
            item["contribution_count"]
            for item in projects[3:]
        )
        other_percentage = other_count / total * 100
        other_bar_width = round(other_percentage)

        bars.append({
            "project_name": "Other projects",
            "contribution_count": other_count,
            "percentage": round(other_percentage, 1),
            "bar_width": other_bar_width,
            "remainder_width": 100 - other_bar_width,
        })

    return {
        "role_label": role_label,
        "unit_label": unit_label,
        "focus_label": focus_label,
        "headline": headline,
        "text": text_value,
        "reflection": reflection,
        "top_project_name": top["project_name"],
        "top_percentage": top["percentage"],
        "project_bars": bars,
        "has_project_data": True,
    }


def project_story(data):
    is_spotter = bool(data.get("is_spotter"))
    is_trapper = bool(data.get("is_trapper"))
    sections = []

    if is_spotter:
        spotter_section = analyse_project_focus(
            data.get("spotter_project_contributions", []),
            "Spotter",
            "classified photos",
        )
        if spotter_section.get("has_project_data"):
            sections.append(spotter_section)

    if is_trapper:
        trapper_section = analyse_project_focus(
            data.get("trapper_project_contributions", []),
            "Trapper",
            "uploaded sequences",
        )
        if trapper_section.get("has_project_data"):
            sections.append(trapper_section)

    if not sections:
        return None

    if len(sections) == 2:
        return story(
            "project_focus",
            "project",
            100,
            "Your project focus · Spotter + Trapper",
            "Two roles, two project paths.",
            (
                "Your classifications and uploads are shown separately because "
                "they represent different kinds of contribution."
            ),
            theme="forest",
            role="both",
            project_sections=sections,
        )

    section = sections[0]
    role_name = section["role_label"]

    return story(
        "project_focus",
        "project",
        100,
        f"Your {role_name} project style · {section['focus_label']}",
        section["headline"],
        section["text"],
        f"{section['top_percentage']:.0f}%",
        f"to {section['top_project_name']}",
        "forest",
        role=role_name.lower(),
        reflection=section["reflection"],
        project_bars=section["project_bars"],
    )


def streak_story(data):
    if not data.get("is_spotter"):
        return None

    spotter = data.get("spotter", {})
    streak = int(spotter.get("longest_streak", 0))

    if streak <= 0:
        return None

    if streak >= 30:
        score = 100
    elif streak >= 14:
        score = 94
    elif streak >= 7:
        score = 84
    elif streak >= 3:
        score = 62
    else:
        score = 50
    start = spotter.get("streak_start")
    end = spotter.get("streak_end")
    day_word = "day" if streak == 1 else "days"

    text_value = (
        f"From {start} to {end}, you contributed every day — your longest "
        "uninterrupted period of Spotter activity."
        if start and end
        else "This was your longest uninterrupted period of Spotter activity."
    )

    return story(
        "streak",
        "moment",
        score,
        "A moment worth remembering",
        f"For {streak} {day_word}, you kept coming back.",
        text_value,
        str(streak),
        f"{day_word} in a row",
        "amber",
        role="spotter",
        reflection=(
            "This streak marks one of the most sustained periods of participation "
            "in your year, when contributing became part of a regular routine."
        ),
    )


def wildlife_story(data):
    if not data.get("is_spotter"):
        return None

    spotter = data.get("spotter", {})
    top_species = spotter.get("top_species", [])

    if not top_species:
        return None

    name, count = top_species[0]
    total = max(int(spotter.get("photos_classified", 0)), 1)
    share = count / total

    return story(
        "wildlife_highlight",
        "wildlife",
        74 + min(share * 30, 18),
        "Your wildlife highlight",
        f"{name} became a familiar presence.",
        f"{name} appeared more often in your classifications than any other species.",
        f"{count:,}",
        f"{name} photos",
        "sage",
        role="spotter",
        reflection=(
            "Although your classifications covered a wider range of wildlife, "
            f"{name} was the species you encountered most often during the year."
        ),
    )


def ranking_story(data):
    if not data.get("is_spotter"):
        return None

    spotter = data.get("spotter", {})
    top_percent = spotter.get("top_percent")
    rank = int(spotter.get("rank", 0))
    total_spotters = int(spotter.get("total_spotters", 0))

    if top_percent is None or rank <= 0 or total_spotters <= 0:
        return None

    if top_percent <= 25:
        if top_percent <= 1:
            score = 100
        elif top_percent <= 5:
            score = 97
        elif top_percent <= 10:
            score = 90
        else:
            score = 78
        title = f"You were among the top {top_percent:.1f}% of Spotters."
        text_value = (
            f"Your activity placed you among MammalWeb's most active Spotters, "
            f"ranked #{rank} of {total_spotters}."
        )
        number = f"Top {top_percent:.1f}%"
        number_label = f"of Spotters in {Report_year}"
    else:
        if top_percent <= 50:
            score = 70
        elif top_percent <= 75:
            score = 60
        else:
            score = 50
        title = f"You ranked #{rank} among {total_spotters} Spotters."
        text_value = (
            "Every classification contributed to the community total and gave "
            f"your {Report_year} activity a place in the wider Spotter community."
        )
        number = f"#{rank}"
        number_label = f"of {total_spotters} Spotters in {Report_year}"

    return story(
        "ranking",
        "achievement",
        score,
        "Your place in the community",
        title,
        text_value,
        number,
        number_label,
        "forest",
        role="spotter",
        reflection=(
            "This places your contribution in the context of the wider MammalWeb "
            "community and shows how your activity compared with other Spotters."
        ),
    )


def spotter_scale_story(data):
    if not data.get("is_spotter"):
        return None

    count = int(data.get("spotter", {}).get("photos_classified", 0))

    if count <= 0:
        return None

    if count >= 2500:
        score = 92
    elif count >= 1000:
        score = 87
    elif count >= 500:
        score = 77
    else:
        score = 58

    return story(
        "spotter_scale",
        "achievement",
        score,
        "The scale of your contribution",
        "You helped examine a year of wildlife footage.",
        "Each classification helped turn raw footage into a usable wildlife record.",
        f"{count:,}",
        "photos classified",
        role="spotter",
        reflection=(
            "The total reflects the cumulative effect of many individual "
            "classifications across the year, rather than a single period of activity."
        ),
    )


def trapper_scale_story(data):
    if not data.get("is_trapper"):
        return None

    count = int(data.get("trapper", {}).get("sequences_uploaded", 0))

    if count <= 0:
        return None

    if count >= 2500:
        score = 93
    elif count >= 1000:
        score = 88
    elif count >= 500:
        score = 78
    else:
        score = 60

    return story(
        "trapper_scale",
        "achievement",
        score,
        "The scale of your contribution",
        "You added a substantial record of wildlife activity.",
        "Each uploaded sequence extended MammalWeb's view of the landscape.",
        f"{count:,}",
        "sequences uploaded",
        role="trapper",
        reflection=(
            "Together, these uploads formed a substantial body of camera-trap "
            "material that could later be reviewed and classified by the community."
        ),
    )


def trapper_sites_story(data):
    if not data.get("is_trapper"):
        return None

    sites = int(data.get("trapper", {}).get("sites", 0))

    if sites <= 0:
        return None

    if sites >= 20:
        score = 92
    elif sites >= 10:
        score = 86
    elif sites >= 5:
        score = 76
    else:
        score = 58

    return story(
        "trapper_sites",
        "achievement",
        score,
        "Across the landscape",
        "Your contribution connected multiple camera sites.",
        "Each site added another viewpoint on wildlife activity.",
        f"{sites:,}",
        "camera sites",
        "forest",
        role="trapper",
        reflection=(
            "Monitoring across multiple sites gave your contribution a wider "
            "geographical reach and added observations from different locations."
        ),
    )


def trapper_effort_story(data):
    if not data.get("is_trapper"):
        return None

    trapper = data.get("trapper", {})
    days = int(trapper.get("camera_days", 0))
    sites = int(trapper.get("sites", 0))

    if days <= 0:
        return None

    if days >= 500:
        score = 95
    elif days >= 250:
        score = 89
    elif days >= 100:
        score = 78
    else:
        score = 60
    site_text = (
        f"Across {sites} site{'s' if sites != 1 else ''}, "
        if sites
        else "Across your sites, "
    )

    return story(
        "camera_effort",
        "achievement",
        score,
        "While you were away",
        "Your cameras kept watching.",
        (
            f"{site_text}the footage you uploaded in {Report_year} represented "
            "sustained camera monitoring."
        ),
        f"{days:,}",
        f"camera-days linked to {Report_year} uploads",
        "sage",
        role="trapper",
        reflection=(
            "Camera-days capture the monitoring effort behind the uploaded footage, "
            "including the time cameras continued collecting observations between visits."
        ),
    )


def trapper_wildlife_story(data):
    if not data.get("is_trapper"):
        return None

    trapper = data.get("trapper", {})
    species_name = trapper.get("top_identified_species")
    sequence_count = int(trapper.get("top_species_sequences", 0))

    if not species_name or sequence_count <= 0:
        return None

    if sequence_count >= 100:
        score = 92
    elif sequence_count >= 50:
        score = 84
    elif sequence_count >= 10:
        score = 74
    else:
        score = 62
    sequence_word = "sequence" if sequence_count == 1 else "sequences"

    return story(
        "trapper_wildlife_highlight",
        "wildlife",
        score,
        "A wildlife highlight from your footage",
        f"{species_name} became a recurring presence.",
        (
            f"Based on available Spotter classifications, {species_name} "
            "was assigned to more of your uploaded sequences than any other "
            "mammal species."
        ),
        f"{sequence_count:,}",
        f"{sequence_word} identified as {species_name}",
        "sage",
        role="trapper",
        reflection=(
            f"This provides a glimpse of the wildlife represented in your uploads, "
            f"with {species_name} appearing most frequently in the classifications "
            "currently available."
        ),
    )


# render email

# The dissertation (4.4) refers to this step as select_stories() - scoring
# every eligible candidate and keeping the top 3 - so it's pulled out here
# as its own function rather than living inline inside build_context().
def select_stories(mandatory_stories, candidate_builders, data, limit=3):
    stories = list(mandatory_stories)

    candidates = []
    for build_candidate in candidate_builders:
        result = build_candidate(data)
        if result is not None:
            candidates.append(result)

    candidates.sort(key=lambda item: item["score"], reverse=True)
    stories.extend(candidates[:limit])

    return stories


def build_context(data):
    context = data.copy()

    mandatory_stories = [participation_story(data)]

    project_focus = project_story(data)
    if project_focus is not None:
        mandatory_stories.append(project_focus)

    candidate_builders = [
        streak_story,
        wildlife_story,
        ranking_story,
        spotter_scale_story,
        trapper_wildlife_story,
        trapper_effort_story,
        trapper_sites_story,
        trapper_scale_story,
    ]

    selected_stories = select_stories(mandatory_stories, candidate_builders, data)

    context.update({
        "subject": f"Your {data['year']} MammalWeb story",
        "preheader": (
            f"A personalised look back at your "
            f"MammalWeb year in {data['year']}."
        ),
        "opening": build_opening(data),
        "stories": selected_stories,
        "story_count": len(selected_stories),
        "impact": build_impact(data),
    })

    return context


def render_email(data, template_path, output_path):
    template_path = Path(template_path)
    output_path = Path(output_path)

    environment = Environment(
        loader=FileSystemLoader(template_path.parent),
        autoescape=select_autoescape(["html", "xml"]),
    )

    template = environment.get_template(template_path.name)
    rendered_html = template.render(**build_context(data))

    output_path.write_text(rendered_html, encoding="utf-8")
    return output_path


# run

if __name__ == "__main__":
    st.cache_data.clear()

    root = Path(__file__).resolve().parent
    template_file = root / "annual_email_template.html"

    if not template_file.exists():
        raise FileNotFoundError(
            "annual_email_template.html must be in the same folder "
            "as this Python file."
        )

    email_data = build_email_data(Person_id)

    print("Spotter projects:", email_data["spotter_project_contributions"])
    print("Trapper projects:", email_data["trapper_project_contributions"])

    if not email_data["is_spotter"] and not email_data["is_trapper"]:
        raise ValueError(
            f"Person {Person_id} has no Spotter or Trapper activity in {Report_year}."
        )

    output_file = root / f"annual_email_{Report_year}_{Person_id}.html"

    render_email(email_data, template_file, output_file)

    selected_ids = []
    for item in build_context(email_data)["stories"]:
        selected_ids.append(item["story_id"])

    print(f"Generated: {output_file.name}")
    print(f"Stories: {', '.join(selected_ids)}")

    webbrowser.open(output_file.resolve().as_uri())