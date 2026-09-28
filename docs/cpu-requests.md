# CPU request audit for sgfdevs-k3s

On 2026-09-28, the three nodes had 22 allocatable CPUs. Running and Pending pods requested about 19.7 CPUs, while `kubectl top nodes` showed about 4 CPUs in use. Requests reserve scheduler capacity; they are not measurements of current consumption. The busiest node had 7,810m requested out of 8,000m, leaving too little room for Twenty's 250m replacement worker.

The usage figures below come from Thanos, which has data back to 2026-09-16. They are the largest five-minute container CPU rate seen per pod over seven days, sampled every 10 to 15 minutes. They can miss short spikes and do not guarantee future capacity. Only CPU requests change in this PR. Memory requests and CPU limits stay the same.

| Workload | CPU request per pod, before to after | Seven-day observed maximum | Scheduled CPU released |
| --- | --- | --- | --- |
| Loki chunks and results caches | 500m to 50m each | 6m and 4m | 900m |
| Outline web servers, two workspaces with two replicas each | 250m to 100m each | 51m across current pods | 600m |
| Twenty workers, two replicas | 250m to 200m each | 140m across current pods | 100m |

Total steady-state reduction: 1,600m. The cache request is controlled by `allocatedCPU` in Loki chart 18.4.4; its memory allocation and cache size are unchanged. The Outline and Twenty reductions leave room above the observed five-minute maxima without reducing their CPU limits.

Other requests were reviewed but left alone:

- Longhorn instance managers request 720m to 960m, set by its default 12% CPU guarantee. Seven-day sampled maxima reached 352m. Longhorn warns that changing this setting while volumes are attached restarts instance managers and may disrupt storage. Do not change it as part of an application rollout.
- KubeBlocks requests 500m and reached 21m in the sampled data. Chart 1.0.2 uses one `resources.cpu` value for both its CPU request and its limit. Lowering the request through that value would also throttle database reconciliation. It needs a chart-level separation or a separately reviewed alternative.
- CloudNativePG and MySQL database pods generally request 250m. A production MySQL pod reached 215m. A blanket reduction would restart stateful services and remove headroom for database bursts; size them per cluster after workload-specific testing.
- The Argo CD application controller reached 275m against a 200m request, and the Kaneo application reached 320m against 200m. These are not good candidates for reductions. The WordPress pods also have peaks well above their requests. Requests need not equal momentary peaks; evaluate sustained demand before raising them.

Twenty's rollout still has required worker anti-affinity and `maxUnavailable: 0`. Lower requests create room on the previously constrained node, but do not remove that rollout deadlock if the node fills up again. Handle the deployment strategy separately.
