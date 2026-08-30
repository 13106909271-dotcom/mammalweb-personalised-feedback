import html
import pandas as pd
import streamlit as st
import altair as alt
from sqlalchemy import create_engine, URL, text

st.set_page_config(page_title="MammalWeb Wrapped", page_icon="🦊", layout="centered")

# settings
Person_id = 16202
Report_year = 2023

Year_start = "2023-01-01"
Data_end = "2024-01-01"
Recent_start = "2023-10-01"

Recent_month_numbers = [10, 11, 12]
Recent_months = ["Oct", "Nov", "Dec"]

Recent_period_label = "October–December 2023"
Recent_period_long = "1 October 2023–31 December 2023"

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

    return create_engine(connection_url, pool_pre_ping=True)

@st.cache_data(ttl=300)
def query_database(sql, params=None):
    engine = get_engine()
    with engine.connect() as connection:
        return pd.read_sql(text(sql), connection, params=params or {})

def recent_params(person_id):
    return {
        "person_id": person_id,
        "start_date": Recent_start,
        "end_date": Data_end
    }

def annual_params(person_id):
    return {
        "person_id": person_id,
        "start_date": Year_start,
        "end_date": Data_end
    }

# SQL queries

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
    result = query_database(sql, recent_params(person_id)).iloc[0]
    return bool(result["is_spotter"]), bool(result["is_trapper"])

def get_photos_classified(person_id, params=None):
    sql = """
    SELECT
        COUNT(DISTINCT photo_id) AS classified_photos
    FROM Animal
    WHERE person_id = :person_id
      AND `timestamp` >= :start_date
      AND `timestamp` < :end_date;
    """

    result = query_database(sql, params or recent_params(person_id))
    return int(result.iloc[0]["classified_photos"])

def get_distinct_species(person_id):
    sql = """
    SELECT
        COUNT(DISTINCT species) AS species_count
    FROM Animal
    WHERE person_id = :person_id
      AND `timestamp` >= :start_date
      AND `timestamp` < :end_date
      AND species IS NOT NULL;
    """

    result = query_database(sql, recent_params(person_id))
    return int(result.iloc[0]["species_count"])

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
              date_sub(activity_date,interval row_num day) as grp
              from numbered_dates),
      streaks AS (
            SELECT  
             MIN(activity_date) AS start_date,
             MAX(activity_date) AS end_date,
             count(activity_date) AS streak_length
             from grouped_dates
             group by grp)
       SELECT
        start_date,
        end_date,
        streak_length
    FROM streaks
    ORDER BY streak_length DESC, end_date DESC
    LIMIT 1;
    """
    result = query_database(sql, recent_params(person_id))

    if result.empty:
        return "", "", 0

    row = result.iloc[0]

    return (
        str(row["start_date"]),
        str(row["end_date"]),
        int(row["streak_length"]),
    )

def get_spotter_rankings(person_id):
    sql = """
    WITH user_counts AS (
        SELECT
            person_id,
            COUNT(DISTINCT photo_id) AS total_classification
        FROM animal
        WHERE `timestamp` >= :start_date
          AND `timestamp` < :end_date
        GROUP BY person_id
    ),

    ranked_users AS (
        SELECT
            person_id,
            total_classification,
            RANK() OVER (
                ORDER BY total_classification DESC
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
        return 0, 0

    row = result.iloc[0]

    return int(row["user_rank"]), int(row["total_users"])

def get_trapper_rankings(person_id):
    sql = """
    WITH user_counts AS (
        SELECT
            person_id,
            COUNT(DISTINCT sequence_id) AS total_uploads
        FROM Photo
        WHERE uploaded >= :start_date
          AND uploaded < :end_date
        GROUP BY person_id
    ),

    ranked_users AS (
        SELECT
            person_id,
            total_uploads,
            RANK() OVER (
                ORDER BY total_uploads DESC
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
        return 0, 0

    row = result.iloc[0]

    return int(row["user_rank"]), int(row["total_users"])

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

    result = query_database(sql, recent_params(person_id))
    species_list = []
    for _, row in result.iterrows():
        species_list.append((str(row["species_name"]), int(row["classified_photos"])))
    return species_list

def get_active_days(person_id):
    sql = """
    SELECT
        COUNT(DISTINCT DATE(`timestamp`)) AS active_days
    FROM Animal
    WHERE person_id = :person_id
      AND `timestamp` >= :start_date
      AND `timestamp` < :end_date;
    """

    result = query_database(sql, recent_params(person_id))

    return int(result.iloc[0]["active_days"])

def get_monthly_spotter(person_id):
    sql = """
    SELECT
        MONTH(`timestamp`) AS month,
        COUNT(DISTINCT photo_id) AS total_classification
    FROM Animal
    WHERE person_id = :person_id
      AND `timestamp` >= :start_date
      AND `timestamp` < :end_date
    GROUP BY MONTH(`timestamp`)
    ORDER BY month;
    """

    result = query_database(sql, recent_params(person_id))

    month_counts = {}
    for _, row in result.iterrows():
        month_counts[int(row["month"])] = int(row["total_classification"])

    values = []
    for month in Recent_month_numbers:
        values.append(month_counts.get(month, 0))
    return values

def get_sequences_uploaded(person_id, params=None):
    sql = """
    SELECT
        COUNT(DISTINCT sequence_id) AS uploaded_sequences
    FROM Photo
    WHERE person_id = :person_id
      AND uploaded >= :start_date
      AND uploaded < :end_date;
    """

    result = query_database(sql, params or recent_params(person_id))
    return int(result.iloc[0]["uploaded_sequences"])

def get_trapper_sites(person_id):
    sql = """
    SELECT
        COUNT(DISTINCT site_id) AS site_count
    FROM photo
    WHERE person_id = :person_id
      AND uploaded >= :start_date
      AND uploaded < :end_date;
    """

    result = query_database(sql, recent_params(person_id))

    return int(result.iloc[0]["site_count"])

def get_monthly_trapper(person_id):
    sql = """
    SELECT
        MONTH(uploaded) AS month,
        COUNT(DISTINCT sequence_id) AS upload_count
    FROM Photo
    WHERE person_id = :person_id
      AND uploaded >= :start_date
      AND uploaded < :end_date
    GROUP BY MONTH(uploaded)
    ORDER BY month;
    """

    result = query_database(sql, recent_params(person_id))

    month_counts = {}
    for _, row in result.iterrows():
        month_counts[int(row["month"])] = int(row["upload_count"])

    values = []
    for month in Recent_month_numbers:
        values.append(month_counts.get(month, 0))
    return values

def get_trapper_locations(person_id):
    sql = """
    SELECT DISTINCT
        s.latitude AS lat,
        s.longitude AS lon
    FROM photo AS p
    JOIN site AS s
        ON p.site_id = s.site_id
    WHERE p.person_id = :person_id
      AND p.uploaded >= :start_date
      AND p.uploaded < :end_date
      AND s.latitude IS NOT NULL
      AND s.longitude IS NOT NULL;
    """

    return query_database(sql, recent_params(person_id))

def get_trapper_identification_summary(person_id):
    # uses classifications currently available, not the final consensus rule
    sql = """
    SELECT
        COUNT(
            DISTINCT CASE
                WHEN o.struc = 'mammal' THEN a.species
            END
        ) AS identified_species,
        COUNT(
            DISTINCT CASE
                WHEN a.photo_id IS NOT NULL THEN p.sequence_id
            END
        ) AS reviewed_sequences
    FROM Photo AS p
    LEFT JOIN Animal AS a
        ON p.photo_id = a.photo_id
    LEFT JOIN Options AS o
        ON a.species = o.option_id
    WHERE p.person_id = :person_id
      AND p.uploaded >= :start_date
      AND p.uploaded < :end_date;
    """

    row = query_database(sql, recent_params(person_id)).iloc[0]

    return (
        int(row["identified_species"] or 0),
        int(row["reviewed_sequences"] or 0),
    )

def get_recent_stats(person_id, is_spotter, is_trapper):
    stats = {
        "classifications": 0,
        "species": 0,
        "uploaded": 0,
        "best_streak": 0,
        "trapper_sites": 0,
        "trapper_species": 0,
    }

    if is_spotter:
        _, _, best_streak = get_longest_streak(person_id)

        stats["classifications"] = get_photos_classified(person_id)
        stats["species"] = get_distinct_species(person_id)
        stats["best_streak"] = best_streak

    if is_trapper:
        identified_species, _ = get_trapper_identification_summary(person_id)

        stats["uploaded"] = get_sequences_uploaded(person_id)
        stats["trapper_sites"] = get_trapper_sites(person_id)
        stats["trapper_species"] = identified_species

    return stats
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
        JOIN Upload AS u
            ON p.upload_id = u.upload_id
        WHERE p.person_id = :person_id
          AND p.uploaded >= :start_date
          AND p.uploaded < :end_date
          AND u.deployment_date IS NOT NULL
          AND u.collection_date IS NOT NULL
    ) AS deployments;
    """

    result = query_database(sql, recent_params(person_id))

    return int(result.iloc[0]["camera_days"])
# Every metric card pairs with a one-line explanation, and they all follow the same
# shape (value vs a set of thresholds -> canned sentence)
MESSAGE_RULES = {
    "active_days": [
        (60, "You were active throughout much of the last three months — an exceptional rhythm of participation."),
        (30, "You returned regularly, making wildlife classification a consistent part of your recent activity."),
        (15, "You maintained a meaningful pattern of participation over the last three months."),
        (5, "You came back on several different days and continued building your contribution."),
        (1, "Every active day added another piece to MammalWeb's wildlife record."),
        (0, "Your next active day will begin a new contribution story."),
    ],
    "classified": [
        (1000, "An exceptional volume of careful observation over the last three months."),
        (500, "You made a substantial recent contribution and helped turn footage into usable data."),
        (100, "Your classifications added real depth to MammalWeb's wildlife records."),
        (20, "You examined a meaningful collection of wildlife footage during this period."),
        (1, "Every classification helped turn a raw image into a more useful record."),
        (0, "Your first classification will begin your Spotter story."),
    ],
    "species": [
        (15, "Your classifications covered an exceptionally broad variety of wildlife."),
        (10, "You encountered a wide range of species during the last three months."),
        (5, "Your recent activity included a varied cast of MammalWeb wildlife."),
        (2, "You identified several different species, adding variety to the dataset."),
        (1, "One identified species is already the beginning of a wildlife story."),
        (0, "Identified species will appear after your first classification."),
    ],
    "streak": [
        (14, "For more than two weeks, you kept returning without missing a day."),
        (7, "You maintained a full week of daily contribution."),
        (3, "You built a clear rhythm of consecutive participation."),
        (2, "You returned on consecutive days and began building momentum."),
        (1, "Every streak begins with one active day."),
        (0, "Your next active day can begin a new streak."),
    ],
    "uploaded": [
        (1000, "Your cameras produced an exceptional volume of wildlife footage during this period."),
        (500, "Your recent uploads created a substantial source of evidence for MammalWeb."),
        (100, "Your cameras captured a meaningful body of wildlife observations."),
        (20, "Your uploaded sequences added a valuable view of wildlife activity."),
        (1, "Every uploaded sequence added another moment from the landscape."),
        (0, "Your first uploaded sequence will begin your Trapper story."),
    ],
    "sites": [
        (10, "Your recent deployments covered an exceptionally broad network of locations."),
        (5, "Your cameras watched wildlife across several parts of the landscape."),
        (3, "Your contribution connected observations from multiple sites."),
        (2, "Your cameras contributed observations from more than one place."),
        (1, "One well-monitored site can still reveal a rich wildlife story."),
        (0, "Your first camera site will appear here."),
    ],
    "trapper_species": [
        (15, "Your reviewed footage revealed an exceptionally broad range of wildlife."),
        (10, "Your cameras captured a wide variety of identified species."),
        (5, "Your reviewed footage included several different species."),
        (2, "Your cameras recorded more than one identified species."),
        (1, "Your reviewed footage has revealed its first identified species."),
        (0, "Identified species will appear as your footage is reviewed."),
    ],
}

def metric_message(value, metric_key):
    # rules are stored high-to-low, so the first threshold value clears wins
    for threshold, message in MESSAGE_RULES[metric_key]:
        if value >= threshold:
            return message
    return MESSAGE_RULES[metric_key][-1][1]

def render_ranking_metric(role_name, rank, total, contribution_desc, container=None):
    target = container if container is not None else st
    target.metric(f"{Report_year} {role_name} ranking", f"#{rank}")
    target.caption(
        f"Ranked #{rank} out of {total} {role_name}s, based on the number "
        f"of different {contribution_desc} in {Report_year}."
    )

def render_community_standing(person_id, is_spotter, is_trapper):
    st.subheader("🏆 Your Community Standing")

    spotter_rank = spotter_total = trapper_rank = trapper_total = 0
    if is_spotter:
        spotter_rank, spotter_total = get_spotter_rankings(person_id)
    if is_trapper:
        trapper_rank, trapper_total = get_trapper_rankings(person_id)

    has_spotter_rank = is_spotter and spotter_rank > 0
    has_trapper_rank = is_trapper and trapper_rank > 0

    if has_spotter_rank and has_trapper_rank:
        col1, col2 = st.columns(2)
        render_ranking_metric("Spotter", spotter_rank, spotter_total, "photos classified", col1)
        render_ranking_metric("Trapper", trapper_rank, trapper_total, "sequences uploaded", col2)
    elif has_spotter_rank:
        render_ranking_metric("Spotter", spotter_rank, spotter_total, "photos classified")
    elif has_trapper_rank:
        render_ranking_metric("Trapper", trapper_rank, trapper_total, "sequences uploaded")
    else:
        st.info("No community ranking is available for this user.")


def recent_monthly_pattern_message(values, activity_name):
    total = sum(values)
    if total <= 0:
        return "New activity will appear here."

    active_months = 0
    for value in values:
        if value > 0:
            active_months += 1

    biggest = max(values)
    busiest_index = values.index(biggest)
    busiest_month = Recent_months[busiest_index]
    busiest_share = biggest / total

    if active_months == 3 and busiest_share < 0.50:
        return f"Your {activity_name} continued across all three months, with {busiest_month} as the busiest."
    elif busiest_share >= 0.70:
        return f"Your {activity_name} was strongly concentrated in {busiest_month}, which accounted for {busiest_share:.0%} of the three-month total."
    elif active_months == 1:
        return f"Your recent {activity_name} was concentrated in {busiest_month}."
    else:
        return f"You contributed during {active_months} of the three months, with {busiest_month} as your busiest month."

def render_quarterly_comparison(person_id, is_spotter, is_trapper):
    st.subheader(f"📈 Compared with Your {Report_year} Average Quarter")
    st.caption(
        f"{Recent_period_label} compared with your average quarter "
        f"across the full {Report_year} calendar year."
    )

    if is_spotter and is_trapper:
        spotter_current = get_photos_classified(person_id, recent_params(person_id))
        spotter_year = get_photos_classified(person_id, annual_params(person_id))
        spotter_average = spotter_year / 4

        trapper_current = get_sequences_uploaded(person_id, recent_params(person_id))
        trapper_year = get_sequences_uploaded(person_id, annual_params(person_id))
        trapper_average = trapper_year / 4

        col1, col2 = st.columns(2)

        with col1:
            difference = spotter_current - spotter_average
            st.metric(
                "Photos classified",
                f"{spotter_current:,}",
                delta=f"{difference:+,.0f} vs your {Report_year} quarterly average"
            )
            st.caption(
                f"Your average quarter in {Report_year}: {spotter_average:,.0f} photos."
            )

        with col2:
            difference = trapper_current - trapper_average
            st.metric(
                "Sequences uploaded",
                f"{trapper_current:,}",
                delta=f"{difference:+,.0f} vs your {Report_year} quarterly average"
            )
            st.caption(
                f"Your average quarter in {Report_year}: {trapper_average:,.0f} sequences."
            )

    elif is_spotter:
        current = get_photos_classified(person_id, recent_params(person_id))
        yearly = get_photos_classified(person_id, annual_params(person_id))
        average = yearly / 4
        difference = current - average

        st.metric(
            "Photos classified",
            f"{current:,}",
            delta=f"{difference:+,.0f} vs your {Report_year} quarterly average"
        )
        st.caption(f"Your average quarter in {Report_year}: {average:,.0f} photos.")

    elif is_trapper:
        current = get_sequences_uploaded(person_id, recent_params(person_id))
        yearly = get_sequences_uploaded(person_id, annual_params(person_id))
        average = yearly / 4
        difference = current - average

        st.metric(
            "Sequences uploaded",
            f"{current:,}",
            delta=f"{difference:+,.0f} vs your {Report_year} quarterly average"
        )
        st.caption(f"Your average quarter in {Report_year}: {average:,.0f} sequences.")

    else:
        st.info("No contribution comparison is available for this user.")


# badges

def make_badge(emoji, category, value, base, step, unit, desc=""):
    if value < base:
        level = 0
        current = 0
        next_level = base
    else:
        level = 1 + (value - base) // step
        current = base + (level - 1) * step
        next_level = current + step

    progress = (value - current) / (next_level - current)

    return {
        "emoji": emoji,
        "category": category,
        "label": "Not yet earned" if level == 0 else f"Level {level}",
        "value": value,
        "unit": unit,
        "progress": min(1.0, max(0.0, progress)),
        "progress_text": (
            f"{max(0, next_level - value):,} more {unit} "
            f"to Level {level + 1}"
        ),
        "desc": desc,
    }

def compute_badges(is_spotter, is_trapper, stats):
    badges = []

    if is_spotter:
        badges.append(
            make_badge(
                "🔍", "Classifier", stats["classifications"], 100, 250,
                "classifications", "Different photos classified during this period."
            )
        )
        badges.append(
            make_badge(
                "🦊", "Species Hunter", stats["species"], 5, 5,
                "species", "Different species identified during this period."
            )
        )
        badges.append(
            make_badge(
                "🔥", "Streak", stats["best_streak"], 7, 7,
                "day streak", "Longest consecutive active period."
            )
        )

    if is_trapper:
        badges.append(
            make_badge(
                "📷", "Trapper", stats["uploaded"], 100, 250,
                "sequences", "Sequences uploaded."
            )
        )
        badges.append(
            make_badge(
                "📍", "Sites Covered", stats["trapper_sites"], 5, 5,
                "sites", "Distinct camera sites."
            )
        )
        badges.append(
            make_badge(
                "🦡", "Wildlife Discoverer", stats["trapper_species"], 5, 5,
                "species", "Different species identified in your uploaded footage."
            )
        )

    return badges

# small display functions

def section_title(text):
    st.markdown(
        f"""
        <div style="border-left:4px solid #FFA751;padding-left:12px;margin-bottom:8px;">
            <span style="font-size:25px;font-weight:bold;color:#FFA751;">
                {html.escape(text)}
            </span>
        </div>
        """,
        unsafe_allow_html=True,
    )

def divider():
    st.markdown("<br>", unsafe_allow_html=True)

st.markdown("""
<style>
.badge-card{text-align:center;color:#e8e8e8;margin-bottom:28px}
.badge-disc{background:linear-gradient(135deg,#FFE259 0%,#FFA751 100%);
border-radius:50%;width:96px;height:96px;margin:0 auto 10px;display:flex;
align-items:center;justify-content:center;box-shadow:0 4px 12px rgba(0,0,0,.25)}
.badge-emoji{font-size:44px}.badge-cat{font-weight:700;font-size:14px;
text-transform:uppercase}.badge-label{font-size:13px;opacity:.85}
.badge-bar-bg{background:rgba(255,255,255,.15);border-radius:6px;height:6px;
width:70%;margin:8px auto 0;overflow:hidden}.badge-bar-fill{background:#FFA751;
height:6px}.badge-prog{font-size:11px;margin-top:6px;opacity:.7}
</style>
""", unsafe_allow_html=True)

# display page

is_spotter, is_trapper = get_role(Person_id)

st.title("🦊 Your MammalWeb Recent Activity")

if not is_spotter and not is_trapper:
    st.warning(
        f"No Spotter or Trapper activity was found for person ID {Person_id} "
        f"during {Recent_period_label}."
    )
    st.stop()
st.markdown("### Welcome back!")
st.markdown(
    f"#### Recent contribution highlights from {Recent_period_label}.")
st.caption(
    f"The dashboard focuses on {Recent_period_label}. Community ranking and "
    f"the quarterly comparison use full-year {Report_year} data as context."
)

if is_spotter and is_trapper:
    st.info("🌟 You were both a **Spotter** and a **Trapper** during this period.")
elif is_spotter:
    st.info("🔍 You were a **Spotter** during this period.")
elif is_trapper:
    st.info("🎥 You were a **Trapper** during this period.")

divider()
render_community_standing(Person_id, is_spotter, is_trapper)

divider()
render_quarterly_comparison(Person_id, is_spotter, is_trapper)

divider()
st.subheader("🏅 Your Recent Achievements")
st.markdown(
    f"Based on your activity from {Recent_period_label}.")
stats = get_recent_stats(Person_id, is_spotter, is_trapper)
badges = compute_badges(is_spotter, is_trapper, stats)

for index in range(0, len(badges), 3):
    columns = st.columns(3)
    for column, badge in zip(columns, badges[index:index + 3]):
        percentage = int(badge["progress"] * 100)
        tooltip = (
            f"{badge['desc']} "
            f"(Currently: {badge['value']:,} {badge['unit']})"
        )
        column.markdown(
            f"""
            <div class="badge-card" title="{html.escape(tooltip)}">
                <div class="badge-disc">
                    <div class="badge-emoji">{badge['emoji']}</div>
                </div>
                <div class="badge-cat">{html.escape(badge['category'])}</div>
                <div class="badge-label">{html.escape(badge['label'])}</div>
                <div class="badge-bar-bg">
                    <div class="badge-bar-fill" style="width:{percentage}%"></div>
                </div>
                <div class="badge-prog">
                    {html.escape(badge['progress_text'])}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

divider()
# spotter display page
if is_spotter:
    st.title("🔍 As a Spotter")

    active_days = get_active_days(Person_id)
    active_days_message = metric_message(active_days, "active_days")
    section_title("Active days in the last three months")
    st.markdown(f"# {active_days}")
    st.markdown(f"#### {active_days_message}")
    divider()

    current_classified = get_photos_classified(Person_id)
    classified_message = metric_message(current_classified, "classified")

    section_title("Photos classified")
    st.markdown(f"# {current_classified:,}")
    st.markdown(
        f"#### {classified_message}"
    )
    divider()

    species = get_distinct_species(Person_id)
    species_message = metric_message(species, "species")
    section_title("Different species identified")
    st.markdown(f"# {species}")
    st.markdown(f"#### {species_message}")
    divider()

    start, end, streak_length = get_longest_streak(Person_id)
    streak_message = metric_message(streak_length, "streak")
    section_title("Longest daily streak")
    st.markdown(f"# {streak_length} days")
    st.markdown(f"#### {streak_message}")

    if streak_length > 0:
        st.markdown(
            f"Your longest streak ran from **{start}** to **{end}**."
        )

    divider()

    section_title(f"Classification activity · {Recent_period_label}")
    monthly_spotter = get_monthly_spotter(Person_id)
    monthly_spotter_df = pd.DataFrame({
        "month": Recent_months,
        "classifications": monthly_spotter,
    })

    spotter_chart = (
        alt.Chart(monthly_spotter_df)
        .mark_bar()
        .encode(
            x=alt.X(
                "month:N",
                sort=Recent_months,
                title=None,
            ),
            y=alt.Y(
                "classifications:Q",
                title="Photos classified",
            ),
            tooltip=[
                alt.Tooltip("month:N", title="Month"),
                alt.Tooltip(
                    "classifications:Q",
                    title="Photos classified",
                    format=",",
                ),
            ],
        )
    )

    st.altair_chart(spotter_chart, use_container_width=True)
    spotter_pattern_message = recent_monthly_pattern_message(
        monthly_spotter,
        "classification activity"
    )
    st.markdown(f"#### {spotter_pattern_message}")
    divider()

    section_title("Your top species")
    top_species = get_top_species_spotter(Person_id)
    for position, (name, count) in enumerate(top_species, 1):
        st.markdown(f"#### **{position}. {name}** — {count} classifications")
    if top_species:
        st.markdown(
            f"#### **{top_species[0][0]}** became your most familiar species."
        )
    divider()
# trapper display page
if is_trapper:
    st.title("🎥 As a Trapper")

    uploaded = get_sequences_uploaded(Person_id)
    uploaded_message = metric_message(uploaded, "uploaded")

    section_title("Sequences uploaded")
    st.markdown(f"# {uploaded:,}")
    st.markdown(
        f"#### {uploaded_message}"
    )
    divider()

    identified_species, reviewed_sequences = get_trapper_identification_summary(Person_id)
    section_title("Wildlife identified so far")
    species_column, reviewed_column = st.columns(2)

    with species_column:
        st.metric("Identified species", identified_species)
        st.caption(metric_message(identified_species, "trapper_species"))

    with reviewed_column:
        st.metric("Reviewed sequences", f"{reviewed_sequences:,}")
        st.caption("Uploaded sequences that have received classifications.")

    st.info(
        "These figures are based only on footage classified so far. They may "
        "increase months after upload as more sequences are reviewed. The final "
        "SQL should use MammalWeb's accepted or consensus classification rule "
        "when classifications conflict."
    )
    divider()

    sites = get_trapper_sites(Person_id)
    effort = get_trapper_effort_days(Person_id)

    site_column, effort_column = st.columns(2)

    with site_column:
        section_title("Camera sites")
        st.markdown(f"# {sites}")
        st.caption(metric_message(sites, "sites"))

    with effort_column:
        section_title("Camera-days")
        st.markdown(f"# {effort:,}")
        st.caption(
            "The combined deployment time linked to footage uploaded during this period.")
    st.markdown(
        f"#### Footage uploaded during this period represented "
        f"**{effort:,} camera-days** of wildlife monitoring across "
        f"**{sites} sites**." )
    divider()

    section_title("Where your cameras were")
    locations = get_trapper_locations(Person_id)

    if locations.empty:
        st.info("No mapped camera locations are available for this period.")
    else:
        st.map(locations)
    st.markdown(
        f"#### Your camera network connected observations from "
        f"**{sites} different sites**."
    )
    divider()

    section_title(f"Uploads · {Recent_period_label}")

    monthly_trapper = get_monthly_trapper(Person_id)

    monthly_trapper_df = pd.DataFrame({
        "month": Recent_months,
        "uploads": monthly_trapper,
    })

    trapper_chart = (
        alt.Chart(monthly_trapper_df)
        .mark_bar()
        .encode(
            x=alt.X(
                "month:N",
                sort=Recent_months,
                title=None,
            ),
            y=alt.Y(
                "uploads:Q",
                title="Uploaded sequences",
            ),
            tooltip=[
                alt.Tooltip("month:N", title="Month"),
                alt.Tooltip(
                    "uploads:Q",
                    title="Uploaded sequences",
                    format=",",
                ),
            ],
        )
    )

    st.altair_chart(trapper_chart, use_container_width=True)

    trapper_pattern_message = recent_monthly_pattern_message(monthly_trapper, "camera-upload activity")
    st.markdown(
        f"#### {trapper_pattern_message}"
    )

st.markdown("---")
st.markdown("### Thanks for being part of MammalWeb 🐾")
st.caption(f"Data period: {Recent_period_long}")