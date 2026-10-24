// Atlas Stream Processing: live pipeline metrics for the dashboard.
//
// Reads the change stream on flowarc.logs and writes one document per stage per minute to
// flowarc.metrics: check results, passes, failures and samples that moved on.
//
// Setup (Atlas UI): Stream Processing -> create a workspace (SP2 is enough), then in its
// Connection Registry add your cluster under the name "flowarc". Then:
//   mongosh "<workspace connection string>" --username <atlas admin> scripts/stream_metrics.js
// Stop it after the demo (sp.flowarc_metrics.stop()) so it stops billing.

const CONN = "flowarc";
const DB = "flowarc";

const pipeline = [
  { $source: { connectionName: CONN, db: DB, coll: "logs" } },
  { $match: { operationType: "insert" } },
  { $replaceRoot: { newRoot: "$fullDocument" } },
  {
    $tumblingWindow: {
      interval: { size: NumberInt(1), unit: "minute" },
      pipeline: [
        {
          $group: {
            _id: "$stage",
            events: { $sum: 1 },
            passed: { $sum: { $cond: [{ $eq: ["$passed", true] }, 1, 0] } },
            failed: { $sum: { $cond: [{ $eq: ["$passed", false] }, 1, 0] } },
            advanced: { $sum: { $cond: [{ $eq: ["$msg", "advanced"] }, 1, 0] } },
            samples: { $addToSet: "$sample" },
          },
        },
      ],
    },
  },
  {
    $set: {
      stage: "$_id",
      window: "$_stream_meta.window.start",
      samples: { $size: "$samples" },
      checks: { $add: ["$passed", "$failed"] },
    },
  },
  { $set: { _id: { $concat: ["$stage", "@", { $toString: "$window" }] } } },
  { $merge: { into: { connectionName: CONN, db: DB, coll: "metrics" } } },
];

if (sp.listStreamProcessors().some((p) => p.name === "flowarc_metrics")) {
  print("flowarc_metrics already exists");
} else {
  sp.createStreamProcessor("flowarc_metrics", pipeline);
}
sp.flowarc_metrics.start();
printjson(sp.flowarc_metrics.stats());
