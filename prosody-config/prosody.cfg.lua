interfaces = { "0.0.0.0" }

admins = { "manager@localhost" }

modules_enabled = {
    "roster"; "saslauth"; "tls"; "dialback"; "disco"; "private"; "vcard"; "compression";
    "legacyauth"; "admin_adhoc"; "pep"; "posix"; "bosh"; "carbons"; "c2s"; "s2s";
    "offline"; "mam"; "csi";
}

VirtualHost "localhost"
    allow_registration = true
    authentication = "internal_plain"
    c2s_require_encryption = false

    users = {
        ["manager@localhost"] = { password = "Fyfsndidr11@" };
        ["stock_worker@localhost"] = { password = "fyfsndidrstock" };
        ["sentiment_worker@localhost"] = { password = "fyfsndidrnews" };
        ["portfolio_worker@localhost"] = { password = "fyfsndidrportfolio" };
        ["financial_news_worker@localhost"] = { password = "fyfsndidrfinancial" };
        ["historical_data_worker@localhost"] = { password = "fyfsndidrhistorical" };
    };

