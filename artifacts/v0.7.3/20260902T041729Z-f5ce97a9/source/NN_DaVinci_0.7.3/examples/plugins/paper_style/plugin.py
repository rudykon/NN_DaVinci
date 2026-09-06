def create_plugin(context):
    """Return theme overrides; NN_DaVinci merges them with its complete base theme."""
    return {
        "font_family": "Georgia, serif",
        "accent": "#7c3aed",
        "node_radius": 4,
        "category_colors": {"attention": "#ede9fe", "convolution": "#dbeafe"},
    }
