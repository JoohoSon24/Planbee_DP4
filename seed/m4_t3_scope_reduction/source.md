# T3. Scope Reduction

: Dev의 구현 지연으로 GD와 범위 조정 후 PM 승인 필요

[원본 일정 보드](/demos/m4_t3_scope_reduction/board)

1. 변경 요청
    
    Dev → Advanced Effects 구현에 이틀 정도 더 필요할 것 같습니다. 그런데 Core Integration도 다음 주에 마쳐야 해서, 지금 계획대로는 Alpha 마감을 맞추기 어렵습니다. 작업 범위를 조정할 수 있을까요?
    
2. 협의 참여 에이전트
    
    Dev, GD
    
3. 협상에 관여하는 담당자별 제약 및 위임 규칙
    
    Dev : 11/23·24 각 8h 가용. Core Integration 8h 필수. Advanced Effects 예상 32h. 두 작업은 독립적. Advanced Effects의 기능 우선순위는 모름.
    
    GD : Core X·Core Integration은 P0 필수, Advanced Effects는 P2 선택. Advanced Effects 제외 시에도 Alpha 필수 요구사항 충족. 범위 축소 제안 가능, 확정 권한 없음.
    
    Art : Advanced FX 총 12h 중 8h 완료, 잔여 4h는 11/23 예정. PM이 Advanced Effects의 Beta 이관을 승인하면 관련 잔여 작업도 자동 이관되며 Art의 별도 Confirm은 필요하지 않음.
    
    QA : 11/25~26 Final QA 16h. Advanced Effects 제외 시 Core X와 Core Integration만 테스트 가능. 기존 일정 변경 없음.
    
    PM : Alpha 기능 범위 축소와 Beta 이관은 명시적 승인 필요.
    
4. 기대하는 협상안(예시)
    
    Dev가 GD에게 선택 기능 여부를 확인하고 Advanced Effects의 Beta 이관을 제안. GD가 범위 축소에 동의하면 PM 승인 요청. 승인 후 승인 후 Dev는 11/23~24 중 가용한 8h에 Core Integration을 수행, Art의 Advanced FX 잔여 작업도 Beta로 이관. QA 일정 유지.
    
5. AI prompt Evaluation
- 협상 상대 식별
- Scope Reduction : 선택 기능 이관을 제대로 제안하는가
- 권한 준수
- 영향 최소화 : Art, QA의 기존 alpha 일정이 유지된다면 불필요한 추가 협상을 요구하지 않는다

