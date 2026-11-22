# T4. Composite Negotiation

[원본 일정 보드](/demos/m4_t4_composite/board)

1. 변경 요청
    
    Art → Character Animation에 하루가 더 필요할 것 같습니다. 그러면 제가 맡은 FX Assets 작업을 예정대로 마치기 어려워져요. 다른 담당자들의 일정에도 영향이 있을 것 같아서 조정하고 싶습니다.
    
2. 협의 참여 에이전트
    
    Art, Dev, QA
    
3. 협상에 관여하는 담당자별 제약 및 위임 규칙
    
    Dev : 11/23·24 각 8h 가용. Anim Integration 8h와 Critical Fix 8h 필수. Anim Integration은 FX Assets가 필요하며, 임시 에셋을 사용하면 임시 Integration 6h와 최종 교체 2h로 분할 가능. 최종 교체는 FX Assets 전달 이후 수행해야 함. Critical Fix는 Anim Integration과 독립적으로 수행 가능.
    
    Art : Character Animation에 추가 8h 필요. 11/20 가용 8h를 추가 작업에 사용하므로 FX Assets의 잔여 4h는 11/23 오전에 수행하고 12:00 전달 가능. 임시 에셋은 11/20 제공 가능.
    
    QA : 11/24 Integration Retest 8h는 최종 에셋이 반영된 Anim Integration 완료 후 진행하는 중간 검증이며, 해당 작업은 Retest 시작 전 영업일까지 완료되어야 함. Retest는 선택적이고 11/25~26 Final QA 16h에 동일 검증 항목이 포함됨. Final QA는 Anim Integration과 Critical Fix가 모두 완료된 후 시작해야 함. Retest 생략은 QA 본인 Confirm 필요.
    
    PM : 기존 범위 내 일정 재배치·중간 검증 생략은 승인 불필요.
    
4. 기대하는 협상안(예시)
    
    Art가 Dev에게 FX Assets 전달 지연을 알림. Dev는 임시 에셋을 활용하여 11/23에 임시 Integration 6h와 Critical Fix 2h, 11/24에 최종 교체 2h와 Critical Fix 6h를 수행하도록 재배치.
    
    최종 Anim Integration이 11/24에 완료되므로 QA의 11/24 Integration Retest는 진행할 수 없음. QA가 Retest 생략을 Confirm하고, 11/25~26 Final QA에서 해당 검증을 수행함.
    
    Art·Dev·QA의 변경 합의 후 확정하며 PM 승인은 필요하지 않음.
    
5. AI prompt Evaluation
- 연쇄 영향 분석을 통한 협상 상대 식별
- 정보 확인 : Dev와 QA의 제약이 누출되지 않았으며 필요한 정보만 요청하는가
- 복합 대안 생성
- 실제 변경 당사자 협상
- 제약 검증 및 권한 준수

