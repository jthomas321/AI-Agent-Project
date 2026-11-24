
# Run with python -m streamlit run app.py
import streamlit as st
import math
import config
from pipeline import run_pipeline
from agents.natural_lang_agent import understand_query


st.set_page_config(
    page_title="Sweetery | Find Your Treat",
    page_icon="🍰",
    layout="wide",
    initial_sidebar_state="collapsed",
)


st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Playfair+Display:wght@500;600;700&display=swap');
@import url('https://fonts.googleapis.com/css2?family=Dangrek&family=Pacifico&display=swap');

:root { --pink: #A47DAB; --pink-dark: #784B84; --cream: #FFF9F3; --cocoa: #49332F; --muted: #897873; --border: #F0E3DC; }

.stApp { background: var(--cream); color: var(--cocoa); font-family: 'DM Sans', sans-serif; }
.block-container { max-width: 1120px; padding-top: 2rem; padding-bottom: 4rem; }
h1 { color: var(--cocoa); font-family: 'Pacifico', cursive !important; }
h2, h3 { color: var(--cocoa); font-family: 'Playfair Display', serif !important; }
.hero { background: linear-gradient(120deg, #D7BFDC, #FFF0DB); padding: 2.5rem; border-radius: 24px; margin: 1rem 0 2rem; border: 1px solid #F5DDE0; }
.hero-eyebrow { text-transform: uppercase; letter-spacing: 3px; color: var(--pink-dark); font-size: 0.75rem; font-weight: 700; }
.hero h1 { font-size: clamp(2.2rem, 5vw, 3.6rem); line-height: 1.15; margin: 0.5rem 0; }
.hero p { color: #795D56; font-size: 1.05rem; max-width: 580px; }
.search-panel { background: white; padding: 1.5rem; border: 1px solid var(--border); border-radius: 20px; margin-bottom: 2rem; }
.dessert-card { background: white; border: 1px solid var(--border); border-radius: 18px; padding: 1.35rem; margin-bottom: 1rem; min-height: 170px; }
.dessert-card h3 { font-size: 1.35rem; margin: 0.5rem 0; }
.price { font-size: 1.5rem; font-weight: 700; color: var(--pink-dark); }
.pill { display: inline-block; padding: 0.3rem 0.65rem; border-radius: 999px; font-size: 0.75rem; font-weight: 700; background: #FBE8ED; color: #99445F; }
.muted { color: var(--muted); font-size: 0.9rem; }

div.stButton > button, div.stFormSubmitButton > button { background: var(--pink); color: white; border: none; border-radius: 12px; font-weight: 700; min-height: 45px; transition: background 0.2s ease; }
div.stButton > button:hover, div.stFormSubmitButton > button:hover { background: var(--pink-dark); color: white; border: none; }


.st-key-menu_button div.stLinkButton > a:hover {
    background-color: #B19BDB;
    color: #49332F;
    border-color: #A48BD9;
}
div[data-testid="stLinkButton"] a {
    background-color: #C5B4E8 !important;
    color: #49332F !important;
    border: 1px solid #B19BDB !important;
    border-radius: 12px !important;
    font-weight: 700 !important;
}

div[data-testid="stLinkButton"] a:hover {
    background-color: #B19BDB !important;
}

div[data-testid="stForm"] { background: white; border: 1px solid var(--border); padding: 1.5rem; border-radius: 20px; }
div[data-testid="stTextInput"] input, div[data-testid="stNumberInput"] input { border-radius: 10px; }
section[data-testid="stSidebar"] { background: var(--cream); }
hr { border-color: var(--border); }

@media (max-width: 640px) { .hero { padding: 1.5rem; } .block-container { padding-left: 1rem; padding-right: 1rem; } }

</style>
""", unsafe_allow_html=True)

# search engine homepage
st.markdown(
    """
    <div class="hero" style="text-align: center;">
        <div style="font-size: 3rem;">🍰</div>
        <h1 style="font-family: 'Pacifico', cursive; font-size: 3.5rem; margin-bottom: 0; color: #49332F;">Sweetery</h1>
        <p style="color: #795D56; font-size: 1.1rem; margin: 0.5rem auto 0; text-align: center; width: 100%; display: block;">Find your perfect dessert.</p>
    </div>
    """,
    unsafe_allow_html=True,
)


# natural language search box
with st.form("search_form"):
    query = st.text_input(
        "Search desserts",
        placeholder="Try chocolate flavored ice cream...",
        label_visibility="collapsed",
    )

    submitted = st.form_submit_button("🔍 Search Sweetery", use_container_width=True)


# process search
if submitted:
    if not query.strip() :
        st.warning("Please enter a dessert search.")
    else:
        try:
            # Check SearXNG availability only for live data mode, matching the original app's behavior.
            if config.DATA_SOURCE != "mock":
                from tools.web_search import check_available
                if not check_available():
                    st.error(
                        f"Live search is not running. Start SearXNG at {config.SEARXNG_URL} (see the README), then try again."
                    )
                    st.stop()
                config.DATA_SOURCE = "live"

            # Interpret query with the natural-language agent. For filter-only searches,
            # pass an empty query; advanced filters below override the returned defaults.
            nlu_result = understand_query(user_query=query.strip())
            request = dict(nlu_result.get("request", {}))

            # Normalize unlimited distance values from the agent to Python None.
            distance = request.get("max_distance_miles")
            if distance is None or (isinstance(distance, str) and distance.strip().lower() in ("null", "none", "")):
                request["max_distance_miles"] = None
            else:
                request["max_distance_miles"] = float(distance)



            st.session_state["search_query"] = query
            with st.status("Searching...", expanded=True) as status:
                def show_progress(stage, message):
                    status.update(label=message)
                    status.write(message)

                output = run_pipeline(request, on_step=show_progress)
                pipeline_state = "error" if output.get("status") == "error" else "complete"
                status.update(label="Search finished", state=pipeline_state, expanded=False)
            st.session_state["output"] = output
        except Exception as exc:
            st.error(f"Something went wrong: {exc}")




def _money(text):
    return text.replace("$", r"\$")


def _positive_money(value):
    try:
        value = float(value)
        return math.isfinite(value) and value > 0
    except (ValueError, TypeError):
        return False


def _display_price(dessert):
    if dessert.get("price_status") == "estimated":
        low, high = dessert.get("price_lower"), dessert.get("price_upper")
        if _positive_money(low) and _positive_money(high) and float(low) <= float(high):
            return f"${float(low):.2f} - ${float(high):.2f} (Estimated)"
        if _positive_money(dessert.get("price")):
            return f"Approx. ${float(dessert['price']):.2f} (Estimated)"
    if _positive_money(dessert.get("price")):
        return f"${float(dessert['price']):.2f}"
    return "Price not yet available"


# pipeline output

def show_output(output):

    top_three = output.get("results", [])[:3]

    if top_three:
        st.header("Top 3 Rankings")

    for item in top_three:

        dessert = item["dessert"]

        with st.container(border=True):

            # Dessert name and ranking
            st.subheader(
                f"#{item['rank']} · {dessert['name']} "
                f"at {dessert['business']}"
            )

            # Larger price
            price = _display_price(dessert)
            st.markdown(
                f"<p style='font-size: 1.7rem; "
                f"font-weight: 700; color: #784B84; "
                f"margin: 0.5rem 0;'>"
                f"{price}</p>",
                unsafe_allow_html=True
            )

            # Address
            if dessert.get("address"):
                st.markdown(
                    f"📍 **Address:** {dessert['address']}"
                )

            # Menu button
            if dessert.get("menu_url"):
                st.link_button(
                    "🍰 Explore Menu",
                    dessert["menu_url"],
                    use_container_width=True
                )
            else:
                st.caption("Menu link unavailable")



        st.divider()



if "output" in st.session_state:
    show_output(st.session_state["output"])
