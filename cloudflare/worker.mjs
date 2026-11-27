export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(dispatch(env, event.scheduledTime, event.cron));
  },
  fetch() {
    return new Response("Equity cockpit scheduled dispatcher", { status: 404 });
  }
};

export async function dispatch(env, scheduledTime, cron) {
  if (env.SCHEDULER_ENABLED !== "true") return;
  const { GITHUB_OWNER, GITHUB_REPO, GITHUB_REF, GITHUB_TOKEN } = env;
  if (![GITHUB_OWNER, GITHUB_REPO, GITHUB_REF, GITHUB_TOKEN].every(Boolean)) {
    throw new Error("Missing GitHub dispatcher configuration");
  }
  const repository = [GITHUB_OWNER, GITHUB_REPO].map(encodeURIComponent).join("/");
  const url =
    "https://api.github.com/repos/" +
    repository +
    "/actions/workflows/update_dashboard.yml/dispatches";
  const isMarketClose = cron === "37 8 * * *";
  const trigger_source = isMarketClose ? "benchmark" : "cloudflare";

  // workerd fetch() does NOT support redirect: "error"; always use "manual" and verify HTTP 204
  const response = await fetch(url, {
    method: "POST",
    redirect: "manual",
    signal: AbortSignal.timeout(20000),
    headers: {
      Authorization: "Bearer " + GITHUB_TOKEN,
      Accept: "application/vnd.github+json",
      "Content-Type": "application/json",
      "User-Agent": "equity-cockpit-scheduler",
      "X-GitHub-Api-Version": "2022-11-28"
    },
    body: JSON.stringify({ ref: GITHUB_REF, inputs: { trigger_source } })
  });

  const receipt = {
    scheduledTime,
    cron,
    trigger_source,
    status: response.status,
    github_request_id: response.headers.get("x-github-request-id")
  };
  if (response.status !== 204) {
    console.error(JSON.stringify({ event: "dispatch_rejected", ...receipt }));
    throw new Error("Workflow dispatch expected HTTP 204, got " + response.status);
  }
  console.log(JSON.stringify({ event: "dispatch_accepted", ...receipt }));
}
