# PHercParis4 winding ray-order audit

Source commit: `fb79b0623f319b5ecc97bcb9f528bfcf36076d02`
Inputs: https://dl.ash2txt.org/datasets/spiral_datasets/PHercParis4/

```bash
scroliq-winding --dataset <spiral-input PHercParis4 root> --out PHercParis4.winding-audit.json
```

```
Winding annotation audit: PARTIAL
collections=460 points=7645 annotated=2232
axial collection-center gap=943.7 slices between 15976.5 and 16920.2
umbilicus ray order: review inversions=2/13700 comparable pairs
  review relative collection=178 point=2106 wind_a=8 xyz=[3244.9, 3302.7, 8879.0] inversions=1/7
  review relative collection=178 point=2108 wind_a=10 xyz=[3242.8, 3362.3, 8879.0] inversions=1/8
  review relative collection=250 point=2607 wind_a=6 xyz=[3258.2, 3097.7, 11432.2] inversions=1/6
  review relative collection=250 point=2609 wind_a=8 xyz=[3237.8, 3160.0, 11432.2] inversions=1/6
- absolute: warn collections=6 points=59 sha256=4e566731f7cb...
- relative: warn collections=300 points=2173 sha256=a3243511d4eb...
- same_winding: warn collections=154 points=5413 sha256=d9be52c5ebb4...
- WARNING WINDING_EMPTY_COLLECTION absolute:collections['4'].points: collection contains no points
- WARNING WINDING_EMPTY_COLLECTION relative:collections['121'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['121']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_EMPTY_COLLECTION relative:collections['138'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['138']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_EMPTY_COLLECTION relative:collections['139'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['139']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_EMPTY_COLLECTION relative:collections['157'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['157']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_EMPTY_COLLECTION relative:collections['161'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['161']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_EMPTY_COLLECTION relative:collections['162'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['162']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_EMPTY_COLLECTION relative:collections['170'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['170']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_EMPTY_COLLECTION relative:collections['172'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['172']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_EMPTY_COLLECTION relative:collections['177'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['177']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_EMPTY_COLLECTION relative:collections['199'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['199']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_EMPTY_COLLECTION relative:collections['204'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['204']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_EMPTY_COLLECTION relative:collections['213'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['213']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_EMPTY_COLLECTION relative:collections['214'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['214']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_EMPTY_COLLECTION relative:collections['218'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['218']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_ROLE_METADATA_MISMATCH relative:collections['219'].metadata.winding_is_absolute: file role is relative but metadata declares an absolute-winding collection
- WARNING WINDING_EMPTY_COLLECTION relative:collections['219'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['219']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_EMPTY_COLLECTION relative:collections['221'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['221']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_EMPTY_COLLECTION relative:collections['225'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['225']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_EMPTY_COLLECTION relative:collections['228'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['228']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_EMPTY_COLLECTION relative:collections['230'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['230']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_EMPTY_COLLECTION relative:collections['231'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['231']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_EMPTY_COLLECTION relative:collections['238'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['238']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_EMPTY_COLLECTION relative:collections['239'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['239']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_EMPTY_COLLECTION relative:collections['240'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['240']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_EMPTY_COLLECTION relative:collections['241'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['241']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_EMPTY_COLLECTION relative:collections['255'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['255']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_EMPTY_COLLECTION relative:collections['256'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['256']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_EMPTY_COLLECTION relative:collections['257'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['257']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_ROLE_METADATA_MISMATCH relative:collections['267'].metadata.winding_is_absolute: file role is relative but metadata declares an absolute-winding collection
- WARNING WINDING_EMPTY_COLLECTION relative:collections['267'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['267']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_EMPTY_COLLECTION relative:collections['268'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['268']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_EMPTY_COLLECTION relative:collections['275'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['275']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_EMPTY_COLLECTION relative:collections['278'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['278']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_ROLE_METADATA_MISMATCH relative:collections['291'].metadata.winding_is_absolute: file role is relative but metadata declares an absolute-winding collection
- WARNING WINDING_EMPTY_COLLECTION relative:collections['291'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['291']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_EMPTY_COLLECTION relative:collections['293'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['293']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_ROLE_METADATA_MISMATCH relative:collections['294'].metadata.winding_is_absolute: file role is relative but metadata declares an absolute-winding collection
- WARNING WINDING_EMPTY_COLLECTION relative:collections['294'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['294']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_ROLE_METADATA_MISMATCH relative:collections['298'].metadata.winding_is_absolute: file role is relative but metadata declares an absolute-winding collection
- WARNING WINDING_EMPTY_COLLECTION relative:collections['298'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['298']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_EMPTY_COLLECTION relative:collections['306'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['306']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_ROLE_METADATA_MISMATCH relative:collections['309'].metadata.winding_is_absolute: file role is relative but metadata declares an absolute-winding collection
- WARNING WINDING_EMPTY_COLLECTION relative:collections['309'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['309']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_EMPTY_COLLECTION relative:collections['310'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['310']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_EMPTY_COLLECTION relative:collections['41'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['41']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_EMPTY_COLLECTION relative:collections['51'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['51']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_EMPTY_COLLECTION relative:collections['52'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['52']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_EMPTY_COLLECTION relative:collections['60'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['60']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_EMPTY_COLLECTION relative:collections['64'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['64']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_ROLE_METADATA_MISMATCH relative:collections['65'].metadata.winding_is_absolute: file role is relative but metadata declares an absolute-winding collection
- WARNING WINDING_EMPTY_COLLECTION relative:collections['65'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['65']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_EMPTY_COLLECTION relative:collections['80'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['80']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_EMPTY_COLLECTION relative:collections['88'].points: collection contains no points
- WARNING WINDING_RELATIVE_TOO_SHORT relative:collections['88']: relative-winding collection needs at least two points to encode a relation
- WARNING WINDING_EMPTY_COLLECTION same_winding:collections['100'].points: collection contains no points
- WARNING WINDING_EMPTY_COLLECTION same_winding:collections['101'].points: collection contains no points
- WARNING WINDING_EMPTY_COLLECTION same_winding:collections['102'].points: collection contains no points
- WARNING WINDING_EMPTY_COLLECTION same_winding:collections['103'].points: collection contains no points
- WARNING WINDING_EMPTY_COLLECTION same_winding:collections['125'].points: collection contains no points
- WARNING WINDING_EMPTY_COLLECTION same_winding:collections['147'].points: collection contains no points
- WARNING WINDING_EMPTY_COLLECTION same_winding:collections['153'].points: collection contains no points
- WARNING WINDING_EMPTY_COLLECTION same_winding:collections['154'].points: collection contains no points
- WARNING WINDING_EMPTY_COLLECTION same_winding:collections['165'].points: collection contains no points
- WARNING WINDING_EMPTY_COLLECTION same_winding:collections['166'].points: collection contains no points
- WARNING WINDING_EMPTY_COLLECTION same_winding:collections['167'].points: collection contains no points
- WARNING WINDING_EMPTY_COLLECTION same_winding:collections['168'].points: collection contains no points
- WARNING WINDING_EMPTY_COLLECTION same_winding:collections['169'].points: collection contains no points
- WARNING WINDING_EMPTY_COLLECTION same_winding:collections['170'].points: collection contains no points
- WARNING WINDING_EMPTY_COLLECTION same_winding:collections['171'].points: collection contains no points
- WARNING WINDING_EMPTY_COLLECTION same_winding:collections['172'].points: collection contains no points
- WARNING WINDING_EMPTY_COLLECTION same_winding:collections['173'].points: collection contains no points
- WARNING WINDING_EMPTY_COLLECTION same_winding:collections['174'].points: collection contains no points
- WARNING WINDING_EMPTY_COLLECTION same_winding:collections['30'].points: collection contains no points
- WARNING WINDING_EMPTY_COLLECTION same_winding:collections['57'].points: collection contains no points
- WARNING WINDING_EMPTY_COLLECTION same_winding:collections['71'].points: collection contains no points
- WARNING WINDING_EMPTY_COLLECTION same_winding:collections['85'].points: collection contains no points
- WARNING WINDING_EMPTY_COLLECTION same_winding:collections['86'].points: collection contains no points
- WARNING WINDING_EMPTY_COLLECTION same_winding:collections['94'].points: collection contains no points
- WARNING WINDING_EMPTY_COLLECTION same_winding:collections['95'].points: collection contains no points
- WARNING WINDING_EMPTY_COLLECTION same_winding:collections['96'].points: collection contains no points
- WARNING WINDING_EMPTY_COLLECTION same_winding:collections['97'].points: collection contains no points
- WARNING WINDING_EMPTY_COLLECTION same_winding:collections['98'].points: collection contains no points
- WARNING WINDING_EMPTY_COLLECTION same_winding:collections['99'].points: collection contains no points
- WARNING WINDING_RAY_ORDER_CANDIDATES ray_order: 2 of 13700 comparable annotation pairs are out of radial order around the umbilicus; review the ranked queue
```

Inversions are review candidates, not errors: folding can legitimately
break ray order. Treat the review queue as a list of annotations to open
in VC3D, and record which were confirmed mis-numbered before citing any
precision figure.
